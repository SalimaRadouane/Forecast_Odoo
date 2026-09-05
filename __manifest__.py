{
    'name': 'Forecast AI',
    'version': '18.0.1.0.0',
    'summary': 'AI-powered forecasting for Odoo',
    'depends': ['sale', 'stock'],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
    'data': [
        'security/ir.model.access.csv',
        'views/sale_forecast.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'forecast_ai/static/src/js/forecast_chart.js',
            'forecast_ai/static/src/xml/forecast_chart.xml',
        ],
    },
}