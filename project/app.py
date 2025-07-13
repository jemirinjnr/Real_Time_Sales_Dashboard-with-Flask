from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import re

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

CSV_PATH = 'Grocery_Inventory_and_Sales_Dataset.csv'

def normalize_name(name):
    name = str(name).lower()
    name = re.sub(r'\b(\d+(ml|l|g|kg))\b', '', name)
    name = re.sub(r'[^a-z0-9 ]+', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def load_products(grouped=True):
    df = pd.read_csv(CSV_PATH)
    df = df.rename(columns={
        'Product_ID': 'id',
        'Product_Name': 'name',
        'Unit_Price': 'price',
        'Stock_Quantity': 'inventory',
        'Sales_Volume': 'sold',
        'Catagory': 'category',
    })
    df['price'] = df['price'].astype(str).str.replace('$', '').str.strip().astype(float)
    df['inventory'] = pd.to_numeric(df['inventory'], errors='coerce').fillna(0).astype(int)
    df['sold'] = pd.to_numeric(df['sold'], errors='coerce').fillna(0).astype(int)

    if 'category' in df.columns:
        df['category'] = df['category'].astype(str).str.strip()

    df['normalized_name'] = df['name'].apply(normalize_name)

    if grouped:
        grouped_df = df.groupby(['normalized_name', 'category'], as_index=False).agg({
            'price': 'mean',
            'inventory': 'sum',
            'sold': 'sum'
        }).rename(columns={'normalized_name': 'name'})
        return grouped_df
    else:
        return df

def save_products(df):
    df = df.rename(columns={
        'id': 'Product_ID',
        'name': 'Product_Name',
        'price': 'Unit_Price',
        'inventory': 'Stock_Quantity',
        'sold': 'Sales_Volume'
    })
    df.to_csv(CSV_PATH, index=False)

@app.route('/')
def index():
    return "Flask server is running. Use /dashboard/admin or /dashboard/customer."

@app.route('/dashboard/<role>')
def dashboard(role):
    if role not in ["admin", "customer"]:
        return "Invalid role.", 404
    page = int(request.args.get('page', 1))
    per_page = 10
    raw_category = request.args.get('category', '').strip()
    category = re.sub(r'[^a-zA-Z& ]+', '', raw_category)
    search_query = request.args.get('search', '').strip().lower()

    full_df = load_products()
    categories = full_df['category'].unique().tolist() if 'category' in full_df.columns else []

    df = full_df.copy()

    if category and 'category' in df.columns:
        df = df[df['category'].astype(str).str.strip().str.lower() == category.lower()]

    if search_query:
        df = df[df['name'].astype(str).str.lower().str.contains(search_query)]

    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    paged_df = df.iloc[start:end]

    display_columns = paged_df.columns[:10].tolist()
    products = paged_df[display_columns].to_dict(orient='records')

    return render_template(
        f"dashboard_{role}.html",
        products=products,
        columns=display_columns,
        page=page,
        total=total,
        per_page=per_page,
        categories=categories,
        selected_category=category,
        search_query=search_query
    )

@app.route('/dashboard/admin/table')
def dashboard_admin_table():
    page = int(request.args.get('page', 1))
    per_page = 10

    raw_category = request.args.get('category', '').strip()
    category = re.sub(r'[^a-zA-Z& ]+', '', raw_category)
    search_query = request.args.get('search', '').strip().lower()

    df = load_products()

    # Filter by category
    if category and 'category' in df.columns:
        df = df[df['category'].astype(str).str.strip().str.lower() == category.lower()]

    # Filter by search
    if search_query:
        df = df[df['name'].astype(str).str.lower().str.contains(search_query)]

    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    paged_df = df.iloc[start:end]

    display_columns = paged_df.columns[:10].tolist()
    products = paged_df[display_columns].to_dict(orient='records')

    return render_template(
        "table_admin.html",
        products=products,
        columns=display_columns,
        page=page,
        per_page=per_page,
        total=total,
        selected_category=category
    )


@app.route('/dashboard/customer/table')
def dashboard_customer_table():
    page = int(request.args.get('page', 1))
    per_page = 10

    raw_category = request.args.get('category', '').strip()
    category = re.sub(r'[^a-zA-Z& ]+', '', raw_category)
    search_query = request.args.get('search', '').strip().lower()

    df = load_products()

    # Filter by category
    if category and 'category' in df.columns:
        df = df[df['category'].astype(str).str.strip().str.lower() == category.lower()]

    # Filter by search
    if search_query:
        df = df[df['name'].astype(str).str.lower().str.contains(search_query)]

    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    paged_df = df.iloc[start:end]

    display_columns = paged_df.columns[:10].tolist()
    products = paged_df[display_columns].to_dict(orient='records')

    return render_template(
        "table_customer.html",
        products=products,
        columns=display_columns,
        page=page,
        per_page=per_page,
        total=total,
        selected_category=category
    )

@app.route('/buy', methods=['POST'])
def buy():
    data = request.json
    product_name = str(data.get('product_name')).lower()

    df = load_products(grouped=False)
    df['normalized_name'] = df['name'].apply(normalize_name)

    match_df = df[(df['normalized_name'] == normalize_name(product_name)) & (df['inventory'] > 0)]

    if match_df.empty:
        return jsonify({"success": False, "error": "Product not available or out of stock"}), 404

    i = match_df.index[0]
    df.at[i, 'inventory'] -= 1
    df.at[i, 'sold'] += 1

    save_products(df)
    socketio.emit('update', {}, to=None, namespace='/')
    return jsonify({"success": True})

@app.route('/restock', methods=['POST'])
def restock():
    data = request.json
    product_name = str(data.get('product_name')).lower()
    quantity = int(data.get('quantity', 0))

    if quantity <= 0:
        return jsonify({"success": False, "error": "Invalid restock quantity"}), 400

    df = load_products(grouped=False)
    df['normalized_name'] = df['name'].apply(normalize_name)

    match_df = df[df['normalized_name'] == normalize_name(product_name)]

    if match_df.empty:
        return jsonify({"success": False, "error": "Product not found"}), 404

    indices = match_df.index.tolist()
    num_items = len(indices)
    base_add = quantity // num_items
    remainder = quantity % num_items

    for idx, i in enumerate(indices):
        add_qty = base_add + (1 if idx < remainder else 0)
        df.at[i, 'inventory'] += add_qty

    save_products(df)
    socketio.emit('update', {}, to=None, namespace='/')
    return jsonify({"success": True})


@socketio.on('connect')
def handle_connect():
    df = load_products()
    display_columns = df.columns[:10].tolist()
    products = df.iloc[:10][display_columns].to_dict(orient='records')
    emit('update', products)

@app.route('/plot/sales')
def plot_sales():
    df = load_products()
    try:
        fig, ax = plt.subplots(figsize=(20, 6), facecolor='#202a39')
        ax.set_facecolor("#202a39")  # Chart background

        bars = ax.bar(df['name'][:10], df['sold'][:10], color='#2ea043')  # GitHub green

        # Set title and labels
        ax.set_title('Sales per Product (Top 10)', fontsize=22, color='#c9d1d9')
        ax.set_ylabel('Units Sold', fontsize=18, color='#c9d1d9')
        ax.set_xlabel('Product Name', fontsize=18, color='#c9d1d9')

        # Ticks styling
        ax.tick_params(axis='x', labelrotation=30, labelsize=14, colors='#c9d1d9')
        ax.tick_params(axis='y', labelsize=14, colors='#c9d1d9')

        # Axis lines
        ax.spines['bottom'].set_color('#c9d1d9')
        ax.spines['left'].set_color('#c9d1d9')
        ax.spines['top'].set_color('#0d1117')
        ax.spines['right'].set_color('#0d1117')

        # Grid styling
        ax.grid(True, color='#30363d', linestyle='--', linewidth=0.5, alpha=0.3)

        # Tight layout & export
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor=fig.get_facecolor())  # Match background
        plt.close(fig)
        buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except Exception as e:
        return f"Error generating chart: {e}", 500

@app.route('/download/inventory')
def download_inventory():
    df = load_products()
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    return send_file(io.BytesIO(buf.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='current_inventory_sales.csv')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
