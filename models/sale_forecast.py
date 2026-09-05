import logging
from collections import defaultdict

import pandas as pd
from prophet import Prophet

from odoo import models, fields, api
from odoo.exceptions import AccessError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class SaleForecast(models.Model):
    _name = 'sale.forecast'
    _description = 'Sales Forecast'

    name = fields.Char()
    date = fields.Date()
    predicted_sales = fields.Float()
    lower_bound = fields.Float()
    upper_bound = fields.Float()
    product_id = fields.Many2one('product.product')

    def _check_can_generate_forecast(self):
        """Only sales managers (or the scheduled cron, running as superuser)
        are allowed to trigger the (expensive) ML training job. Read access
        alone (granted to salesmen) is not enough.
        """
        if self.env.su:
            return
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise AccessError(_(
                "Only Sales Managers are allowed to generate sales forecasts."
            ))

    def generate_product_forecast(self):
        self._check_can_generate_forecast()

        Forecast = self.env['sale.forecast']

        Forecast.search([
            ('date', '>=', fields.Date.today())
        ]).unlink()

        self.env.cr.execute("""
            SELECT
                sol.product_id,
                DATE(so.date_order) as order_date,
                SUM(sol.product_uom_qty) as qty
            FROM sale_order_line sol
            JOIN sale_order so ON sol.order_id = so.id
            WHERE so.state IN ('sale', 'done')
              AND sol.product_id IS NOT NULL
            GROUP BY sol.product_id, DATE(so.date_order)
            ORDER BY sol.product_id, order_date
        """)

        rows = self.env.cr.fetchall()

        data_map = defaultdict(list)

        for product_id, order_date, qty in rows:
            data_map[product_id].append({
                'ds': order_date,
                'y': qty
            })

        results = []

        for product_id, data in data_map.items():

            if len(data) < 10:
                continue

            try:
                df = pd.DataFrame(data)
                df['ds'] = pd.to_datetime(df['ds'])
                df['y'] = pd.to_numeric(df['y'])

                df = df.groupby('ds', as_index=False)['y'].sum()

                model = Prophet(
                    yearly_seasonality=True,
                    weekly_seasonality=True,
                    daily_seasonality=False
                )

                model.fit(df)

                # Anchor the forecast window on *today*, not on the last
                # date present in the historical training data: if sales
                # data hasn't been updated in a while (or the cron didn't
                # run for some days), make_future_dataframe(periods=30)
                # would otherwise keep producing a 30-day window that
                # drifts further into the past relative to "today", and
                # get_forecast_kpis (which filters on date >= today) would
                # silently match nothing.
                last_history_date = df['ds'].max()
                today = pd.Timestamp(fields.Date.today())
                horizon_end = today + pd.Timedelta(days=29)

                if horizon_end <= last_history_date:
                    # Historical data already extends past our 30-day
                    # target window (e.g. backfilled/future-dated data) —
                    # periods=1 keeps make_future_dataframe a no-op and we
                    # simply select the desired window below.
                    periods = 1
                else:
                    periods = (horizon_end - last_history_date).days

                future = model.make_future_dataframe(periods=periods, freq='D')
                forecast = model.predict(future)
            except Exception:
                # A single product with degenerate/insufficient data should
                # not prevent forecasts from being generated for the others.
                _logger.exception(
                    "Prophet forecast failed for product_id=%s, skipping.",
                    product_id,
                )
                continue

            product = self.env['product.product'].browse(product_id)

            forecast_window = forecast[
                (forecast['ds'] >= today) & (forecast['ds'] <= horizon_end)
            ]

            for row in forecast_window.itertuples():

                pred = max(0, row.yhat)
                lower = max(0, row.yhat_lower)
                upper = max(0, row.yhat_upper)

                results.append({
                    'name': f'Forecast {product.name}',
                    'product_id': product.id,
                    'date': row.ds.date(),
                    'predicted_sales': round(pred, 2),
                    'lower_bound': round(lower, 2),
                    'upper_bound': round(upper, 2),
                })

        if results:
            Forecast.create(results)

    @api.model
    def get_forecast_chart_data(self, product_id=None):
        domain = []
        if product_id:
            domain.append(('product_id', '=', product_id))
        records = self.search(domain, order='date asc')
        return [
            {
                'date': rec.date.strftime('%Y-%m-%d'),
                'predicted_sales': rec.predicted_sales,
                'lower_bound': rec.lower_bound,
                'upper_bound': rec.upper_bound,
                'product': rec.product_id.name,
                'product_id': rec.product_id.id,
            }

            for rec in records
        ]

    @api.model
    def get_forecast_kpis(self, product_id=None):
        domain = [
            ("date", ">=", fields.Date.today())
        ]

        if product_id:
            domain.append(("product_id", "=", product_id))

        forecasts = self.search(domain)

        forecast_30_days = sum(
            forecasts.mapped("predicted_sales")
        )

        forecast_revenue = sum(
            forecast.predicted_sales * forecast.product_id.lst_price
            for forecast in forecasts
        )

        # Single pass aggregation instead of re-filtering the whole
        # recordset once per distinct product (O(n) instead of O(n^2)).
        demand_by_product = defaultdict(float)
        available_by_product = {}

        for forecast in forecasts:
            product = forecast.product_id
            demand_by_product[product.id] += forecast.predicted_sales
            available_by_product[product.id] = product.qty_available

        stockouts = sum(
            1
            for product_id, predicted_demand in demand_by_product.items()
            if predicted_demand > available_by_product[product_id]
        )

        return {
            "forecast_30_days": round(forecast_30_days, 2),
            "forecast_revenue": round(forecast_revenue, 2),
            "stockouts": stockouts,
            "confidence": self._compute_forecast_confidence(forecasts),
        }

    def _compute_forecast_confidence(self, forecasts):
        """Derive an approximate confidence percentage from Prophet's own
        prediction interval width, instead of showing a hardcoded value.

        A narrow interval relative to the predicted value means Prophet is
        confident; a wide one means the opposite. This is only an
        approximation meant for display purposes, not a statistical
        guarantee.
        """
        relative_widths = []

        for forecast in forecasts:
            if not forecast.predicted_sales:
                continue
            width = forecast.upper_bound - forecast.lower_bound
            relative_widths.append(width / forecast.predicted_sales)

        if not relative_widths:
            return 0.0

        avg_relative_width = sum(relative_widths) / len(relative_widths)
        confidence = max(0.0, min(100.0, 100.0 * (1 - avg_relative_width / 2)))

        return round(confidence, 1)
