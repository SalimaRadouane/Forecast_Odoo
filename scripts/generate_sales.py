# ---------------------------------------------------
# Demo data generator for the Forecast AI module.
#
# This is NOT a standalone script: it is meant to be pasted/exec'd inside
# the Odoo interactive shell (`make shell`), which is the only place where
# `env` is available as an implicit global (see server/odoo/cli/shell.py).
#
# Usage:
#   make shell
#   >>> exec(open('prophet-addons/forecast_ai/scripts/generate_sales.py').read())
#
# Running it any other way (e.g. `python3 generate_sales.py`) will fail
# with a NameError on `env`.
# ---------------------------------------------------

import datetime

# ---------------------------------------------------
# CREATE CUSTOMERS
# ---------------------------------------------------

customer_ids = []

for i in range(50):
    partner = env['res.partner'].create({
        'name': 'Forecast Customer %s' % i,
        'customer_rank': 1,
    })
    customer_ids.append(partner.id)

# ---------------------------------------------------
# CREATE PRODUCTS
# ---------------------------------------------------

product_ids = []

for i in range(20):
    product = env['product.product'].create({
        'name': 'Forecast Product %s' % i,
        'list_price': i * 50 + 100,
    })
    product_ids.append(product.id)

# ---------------------------------------------------
# GENERATE SALES ORDERS
# ---------------------------------------------------

start_date = datetime.datetime(2025, 1, 1)

for i in range(1000):

    order_date = start_date + datetime.timedelta(days=(i % 365))

    partner_id = customer_ids[i % len(customer_ids)]

    lines = []

    number_of_lines = (i % 5) + 1

    for j in range(number_of_lines):

        product = env['product.product'].browse(
            product_ids[j % len(product_ids)]
        )

        if order_date.month in [6, 7, 8]:
            qty = 10 + j
        else:
            qty = 2 + j

        lines.append((0, 0, {
            'product_id': product.id,
            'name': product.name,
            'product_uom_qty': qty,
            'price_unit': product.list_price,
        }))

    sale_order = env['sale.order'].create({
        'partner_id': partner_id,
        'order_line': lines,
    })

    sale_order.action_confirm()

    # Forcer la date après confirmation
    env.cr.execute("""
        UPDATE sale_order
           SET date_order = %s
         WHERE id = %s
    """, (order_date, sale_order.id))

env.cr.commit()

print("1000 SALES ORDERS CREATED")