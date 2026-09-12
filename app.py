from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import os

app = Flask(__name__)
DB_NAME = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            lat REAL,
            lng REAL,
            debt REAL DEFAULT 0,
            visited INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            total_amount REAL,
            paid_amount REAL,
            debt_amount REAL,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients (id)
        )
    ''')
    
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN debt_amount REAL")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN paid_amount REAL")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            product_id INTEGER,
            quantity INTEGER,
            price REAL,
            FOREIGN KEY (order_id) REFERENCES orders (id),
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/clients', methods=['GET', 'POST'])
def handle_clients():
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        data = request.json
        cursor.execute(
            'INSERT INTO clients (name, phone, lat, lng, debt, visited) VALUES (?, ?, ?, ?, 0, 0)',
            (data.get('name'), data.get('phone'), data.get('lat'), data.get('lng'))
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    clients = cursor.execute('SELECT * FROM clients').fetchall()
    conn.close()
    return jsonify([dict(row) for row in clients])

@app.route('/api/clients/<int:client_id>', methods=['PUT'])
def update_client(client_id):
    try:
        data = request.json
        name = data.get('name')
        phone = data.get('phone')
        lat = data.get('lat')
        lng = data.get('lng')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE clients SET name = ?, phone = ?, lat = ?, lng = ? WHERE id = ?',
            (name, phone, lat, lng, client_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/products', methods=['GET', 'POST'])
def handle_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    if request.method == 'POST':
        data = request.json
        cursor.execute(
            'INSERT INTO products (name, price, stock) VALUES (?, ?, ?)',
            (data.get('name'), data.get('price'), data.get('stock'))
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    products = cursor.execute('SELECT * FROM products').fetchall()
    conn.close()
    return jsonify([dict(row) for row in products])

@app.route('/api/system_stats', methods=['GET'])
def system_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    total_sales_res = cursor.execute("SELECT SUM(total_amount) FROM orders WHERE date(date) = date('now', 'localtime')").fetchone()
    total_sales = total_sales_res[0] if total_sales_res[0] else 0
    total_debt_res = cursor.execute("SELECT SUM(debt) FROM clients").fetchone()
    total_debt = total_debt_res[0] if total_debt_res[0] else 0
    total_clients_res = cursor.execute("SELECT COUNT(*) FROM clients").fetchone()
    total_clients = total_clients_res[0] if total_clients_res[0] else 0
    visited_clients_res = cursor.execute("SELECT COUNT(*) FROM clients WHERE visited = 1").fetchone()
    visited_clients = visited_clients_res[0] if visited_clients_res[0] else 0
    rate = int((visited_clients / total_clients * 100)) if total_clients > 0 else 0
    conn.close()
    return jsonify({"total_sales": total_sales, "total_debt": total_debt, "rate": rate})

@app.route('/api/visit_with_order', methods=['POST'])
def visit_with_order():
    try:
        data = request.json
        client_id = data.get('client_id')
        items = data.get('items', [])
        paid_val = data.get('paid_amount')
        paid_amount = float(paid_val) if paid_val is not None and paid_val != "" else 0.0
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        for item in items:
            prod = cursor.execute('SELECT stock, name FROM products WHERE id = ?', (item['product_id'],)).fetchone()
            if not prod:
                conn.close()
                return jsonify({"status": "error", "message": "المنتج غير موجود في المخزون"}), 400
            if prod['stock'] < item['quantity']:
                conn.close()
                return jsonify({"status": "error", "message": f"الكمية المطلوبة ({item['quantity']}) للمنتج ({prod['name']}) أكبر من المخزون المتبقي ({prod['stock']})!"}), 400

        total_amount = sum(float(item['quantity']) * float(item['price']) for item in items)
        debt_amount = total_amount - paid_amount
        
        cursor.execute(
            'INSERT INTO orders (client_id, total_amount, paid_amount, debt_amount) VALUES (?, ?, ?, ?)',
            (client_id, total_amount, paid_amount, debt_amount)
        )
        order_id = cursor.lastrowid
        
        for item in items:
            cursor.execute(
                'INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)',
                (order_id, item['product_id'], item['quantity'], item['price'])
            )
            cursor.execute(
                'UPDATE products SET stock = stock - ? WHERE id = ?',
                (item['quantity'], item['product_id'])
            )
            
        cursor.execute(
            'UPDATE clients SET debt = debt + ?, visited = 1 WHERE id = ?',
            (debt_amount, client_id)
        )
        
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/pay_debt', methods=['POST'])
def pay_debt():
    try:
        data = request.json
        client_id = data.get('client_id')
        payment = float(data.get('payment', 0))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE clients SET debt = debt - ? WHERE id = ?', (payment, client_id))
        conn.commit()
        conn.close()
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/client_history/<int:client_id>', methods=['GET'])
def client_history(client_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    client = cursor.execute('SELECT * FROM clients WHERE id = ?', (client_id,)).fetchone()
    
    orders_query = '''
        o.id as order_id, o.total_amount, o.paid_amount, o.debt_amount, o.date,
        p.name as product_name, oi.quantity, oi.price
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN products p ON oi.product_id = p.id
        WHERE o.client_id = ?
        ORDER BY o.date DESC
    '''
    orders = cursor.execute(f'SELECT {orders_query}', (client_id,)).fetchall()
    
    conn.close()
    
    return jsonify({
        "client": dict(client),
        "orders": [dict(row) for row in orders]
    })

@app.route('/api/backup_db', methods=['GET'])
def backup_db():
    if os.path.exists(DB_NAME):
        return send_file(DB_NAME, as_attachment=True)
    return "Database not found", 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)