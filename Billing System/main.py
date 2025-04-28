import os
import sys
import sqlite3
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import pandas as pd
import threading
import logging
import re # Import regex for mobile validation
import signal
import atexit
from werkzeug.serving import make_server

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask app initialization
# Ensure static folder and template folder are correctly specified relative to your app's structure
app = Flask(__name__, static_folder='static', template_folder='templates')

# --- Configuration ---
# Define allowed payment modes
PAYMENT_MODES = ["CASH", "ACCOUNT", "UPI", "CARD"] # Adjust as needed

# --- Database Handling ---
def get_db_path():
    """Determines the correct path for the database file."""
    if getattr(sys, 'frozen', False):
        # Running as a bundled executable (e.g., PyInstaller)
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as a normal Python script
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'billing_data.db')

def column_exists(cursor, table_name, column_name):
    """Checks if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [column[1] for column in cursor.fetchall()]
    return column_name in columns

def setup_database():
    """Sets up the database schema, creating tables and altering if necessary."""
    db_path = get_db_path()
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        logger.info(f"Database connected at: {db_path}")

        # --- Schema migration/creation for bills table ---
        cursor.execute("PRAGMA table_info(bills)")
        bills_columns = [column[1] for column in cursor.fetchall()]

        # Rename payment_mode to advance_payment_mode if necessary
        if 'payment_mode' in bills_columns and 'advance_payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills RENAME COLUMN payment_mode TO advance_payment_mode")
                logger.info("Renamed 'payment_mode' to 'advance_payment_mode' in 'bills' table.")
            except sqlite3.OperationalError as e:
                 logger.warning(f"Could not rename column 'payment_mode': {e}")

        # Add advance_payment_mode if neither old nor new name exists
        if 'advance_payment_mode' not in bills_columns and 'payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills ADD COLUMN advance_payment_mode TEXT")
                logger.info("Added 'advance_payment_mode' column to 'bills' table.")
            except sqlite3.OperationalError as e:
                 logger.warning(f"Could not add column 'advance_payment_mode': {e}")

        # Add amount_due_payment_mode if it doesn't exist
        if 'amount_due_payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills ADD COLUMN amount_due_payment_mode TEXT")
                logger.info("Added 'amount_due_payment_mode' column to 'bills' table.")
            except sqlite3.OperationalError as e:
                 logger.warning(f"Could not add column 'amount_due_payment_mode': {e}")

        # Define the final bills table schema (used if table doesn't exist)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number TEXT UNIQUE NOT NULL,
            customer_name TEXT,
            mobile_number TEXT,
            product_size TEXT,
            order_date TEXT,
            delivery_date TEXT,
            current_status TEXT,
            total_price REAL,
            advance_payment_mode TEXT,
            advance_amount REAL DEFAULT 0,
            amount_due REAL,
            payment_status TEXT,
            amount_due_payment_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'bills' table schema.")

        # --- Schema migration/creation for income table ---
        if not column_exists(cursor, 'income', 'payment_mode'):
             try:
                cursor.execute("ALTER TABLE income ADD COLUMN payment_mode TEXT")
                logger.info("Added 'payment_mode' column to 'income' table.")
             except sqlite3.OperationalError as e:
                 logger.warning(f"Could not add column 'payment_mode' to 'income': {e}")

        # Define the final income table schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            payment_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'income' table schema.")

        # --- Schema for expenses table ---
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'expenses' table schema.")

        conn.commit()
        logger.info("Database setup/migration check completed successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database error during setup: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close(); logger.info("Database connection closed.")

# --- Utility Functions ---
def generate_serial_number():
    """Generates a unique serial number based on date and sequence."""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    date_prefix = datetime.now().strftime('%Y%m%d')
    cursor.execute(
        "SELECT serial_number FROM bills WHERE serial_number LIKE ? ORDER BY serial_number DESC LIMIT 1",
        (f"{date_prefix}%",)
    )
    result = cursor.fetchone()
    counter = 1
    if result:
        try: counter = int(result[0][-3:]) + 1
        except (ValueError, IndexError): logger.warning(f"Could not parse SN counter: {result[0]}")
    new_serial = f"{date_prefix}{counter:03d}"
    conn.close()
    logger.info(f"Generated serial number: {new_serial}")
    return new_serial

# --- Validation Functions ---
def validate_mobile_number(mobile):
    """Validates mobile number format (10 digits, not starting with 0)."""
    if not mobile: return True, None # Allow empty
    pattern = r"^[1-9]\d{9}$"
    if isinstance(mobile, str) and re.fullmatch(pattern, mobile): return True, None
    else: return False, "Mobile number must be exactly 10 digits and cannot start with 0."

def validate_payment_mode(mode, allow_empty=False):
    """Validates payment mode against the allowed list."""
    if not mode and allow_empty: return True, None
    if mode and mode in PAYMENT_MODES: return True, None
    elif not mode and not allow_empty: return False, "Payment mode is required."
    else: return False, f"Invalid Payment Mode. Allowed: {', '.join(PAYMENT_MODES)}."

def validate_amounts(total_price, advance_amount):
    """Checks if total_price and advance_amount are valid numbers and advance <= total."""
    try:
        total_p = float(total_price)
        advance_a = float(advance_amount)
        if total_p < 0: return False, "Total price cannot be negative."
        if advance_a < 0: return False, "Advance amount cannot be negative."
        if advance_a > total_p: return False, "Advance amount cannot be greater than total price."
        return True, None
    except (ValueError, TypeError, AttributeError):
        return False, "Invalid number format for Total Price or Advance Amount."

# --- Flask Page Routes ---
@app.route('/')
def index():
    """Renders the main Bills page."""
    return render_template('index.html')

@app.route('/income')
def income_page():
    """Renders the Income page."""
    return render_template('incometbl.html')

@app.route('/expenses')
def expenses_page():
    """Renders the Expenses page."""
    return render_template('expencetbl.html')

@app.route('/stats')
def stats_page():
    """Renders the Statistics page."""
    return render_template('stat.html')

# --- Flask API Routes ---

# Configuration APIs
@app.route('/api/payment-modes', methods=['GET'])
def get_payment_modes():
    """Returns the list of allowed payment modes."""
    return jsonify(PAYMENT_MODES)


# Bill APIs
@app.route('/api/bills', methods=['GET'])
def get_bills():
    """Fetches all bills, ordered by latest first."""
    conn = sqlite3.connect(get_db_path())
    try:
        bills = pd.read_sql_query("SELECT * FROM bills ORDER BY id DESC", conn)
        return jsonify(bills.to_dict('records'))
    except Exception as e:
        logger.error(f"API Error fetching bills: {e}")
        return jsonify({"success": False, "message": "Error fetching bills"}), 500
    finally: conn.close()

@app.route('/api/bills', methods=['POST'])
def add_bill():
    """Adds a new bill with validation and auto-generates serial number."""
    data = request.json
    if not data: return jsonify({"success": False, "message": "Invalid request data"}), 400

    # --- Validation ---
    is_valid_mobile, mobile_error = validate_mobile_number(data.get('mobile_number'))
    if not is_valid_mobile: return jsonify({"success": False, "message": mobile_error}), 400
    required_fields = ['customer_name', 'order_date', 'delivery_date', 'current_status',
                       'total_price', 'advance_payment_mode', 'payment_status']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields: return jsonify({"success": False, "message": f"Missing fields: {', '.join(missing_fields)}"}), 400
    is_valid_adv_mode, adv_mode_error = validate_payment_mode(data.get('advance_payment_mode'), allow_empty=False)
    if not is_valid_adv_mode: return jsonify({"success": False, "message": adv_mode_error}), 400
    is_valid_amounts, amount_error = validate_amounts(data.get('total_price'), data.get('advance_amount', '0'))
    if not is_valid_amounts: return jsonify({"success": False, "message": amount_error}), 400

    total_price = float(data['total_price'])
    advance_amount = float(data.get('advance_amount', 0))
    advance_payment_mode = data['advance_payment_mode']
    product_size = data.get('product_size')

    # --- Logic ---
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    generated_serial_number = generate_serial_number()
    amount_due = total_price - advance_amount

    try:
        cursor.execute('''
        INSERT INTO bills (serial_number, customer_name, mobile_number, product_size,
                           order_date, delivery_date, current_status, total_price,
                           advance_payment_mode, advance_amount, amount_due, payment_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            generated_serial_number, data['customer_name'], data.get('mobile_number'),
            data.get('product_size'), data['order_date'], data['delivery_date'],
            data['current_status'], total_price, advance_payment_mode,
            advance_amount, amount_due, data['payment_status']
        ))
        logger.info(f"Inserted bill SN: {generated_serial_number}")

        if advance_amount > 0:
            cursor.execute('''
            INSERT INTO income (date, description, amount, payment_mode)
            VALUES (?, ?, ?, ?)
            ''', ( data['order_date'], f"Advance from {data['customer_name']} (SN: {generated_serial_number})", advance_amount, advance_payment_mode ))
            logger.info(f"Added advance income SN: {generated_serial_number}, Mode: {advance_payment_mode}")

        conn.commit()
        result = {"success": True, "message": "Bill added", "serial_number": generated_serial_number}
        http_status = 201
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding bill: {e}")
        result = {"success": False, "message": f"Error: {str(e)}"}
        http_status = 500
    finally: 
        conn.close()
    return jsonify(result), http_status


@app.route('/api/bills/<int:bill_id>', methods=['PUT'])
def update_bill(bill_id):
    """Updates an existing bill with validation."""
    data = request.json
    if not data: return jsonify({"success": False, "message": "Invalid request data"}), 400

    # --- Validation ---
    is_valid_mobile, mobile_error = validate_mobile_number(data.get('mobile_number'))
    if not is_valid_mobile: return jsonify({"success": False, "message": mobile_error}), 400
    required_fields = ['serial_number','customer_name', 'order_date', 'delivery_date', 'current_status',
                       'total_price', 'advance_payment_mode', 'payment_status']
    missing_fields = [field for field in required_fields if not data.get(field)]
    if missing_fields: return jsonify({"success": False, "message": f"Missing fields: {', '.join(missing_fields)}"}), 400
    is_valid_adv_mode, adv_mode_error = validate_payment_mode(data.get('advance_payment_mode'), allow_empty=False)
    if not is_valid_adv_mode: return jsonify({"success": False, "message": adv_mode_error}), 400
    is_valid_amounts, amount_error = validate_amounts(data.get('total_price'), data.get('advance_amount', '0'))
    if not is_valid_amounts: return jsonify({"success": False, "message": amount_error}), 400

    total_price = float(data['total_price'])
    advance_amount = float(data.get('advance_amount', 0))
    advance_payment_mode = data['advance_payment_mode']
    payment_status = data['payment_status']
    amount_due_payment_mode = data.get('amount_due_payment_mode') # Get from request
    product_size = data.get('product_size')

    # Validate Amount Due Payment Mode *only* if status is PAID
    if payment_status == 'PAID':
        is_valid_due_mode, due_mode_error = validate_payment_mode(amount_due_payment_mode, allow_empty=False) # Must not be empty if paid
        if not is_valid_due_mode:
             return jsonify({"success": False, "message": f"Amount Due Payment Mode Error: {due_mode_error}"}), 400
    else:
        amount_due_payment_mode = None # Ensure it's null if not paid

    # --- Logic ---
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT payment_status, amount_due, advance_amount, serial_number, customer_name FROM bills WHERE id = ?", (bill_id,))
    current_bill = cursor.fetchone()
    if not current_bill: conn.close(); return jsonify({"success": False, "message": "Bill not found"}), 404

    new_amount_due = total_price - advance_amount

    try:
        cursor.execute('''
        UPDATE bills SET
            serial_number = ?, customer_name = ?, mobile_number = ?, product_size = ?,
            order_date = ?, delivery_date = ?, current_status = ?, total_price = ?,
            advance_payment_mode = ?, advance_amount = ?, amount_due = ?, payment_status = ?,
            amount_due_payment_mode = ?
        WHERE id = ?
        ''', (
            data['serial_number'], data['customer_name'], data.get('mobile_number'),
            data.get('product_size'), data['order_date'], data['delivery_date'],
            data['current_status'], total_price, advance_payment_mode,
            advance_amount, new_amount_due, payment_status,
            amount_due_payment_mode, # Save the due mode
            bill_id
        ))
        logger.info(f"Updated bill ID: {bill_id}")

        current_payment_status_db = current_bill['payment_status']
        final_payment_amount_db = current_bill['amount_due']

        # Add final payment to income ONLY if status changes to PAID and there was an amount due
        if payment_status == 'PAID' and current_payment_status_db == 'NOT PAID' and final_payment_amount_db > 0:
            payment_date = datetime.now().strftime('%Y-%m-%d')
            # amount_due_payment_mode is already validated above for the PAID status
            cursor.execute('''
            INSERT INTO income (date, description, amount, payment_mode)
            VALUES (?, ?, ?, ?)
            ''', ( payment_date, f"Final payment from {data['customer_name']} (SN: {data['serial_number']})", final_payment_amount_db, amount_due_payment_mode ))
            logger.info(f"Added final payment income ID: {bill_id}, Amount: {final_payment_amount_db}, Mode: {amount_due_payment_mode}")

        conn.commit()
        result = {"success": True, "message": "Bill updated"}
        http_status = 200
    except sqlite3.IntegrityError as e: 
        conn.rollback()
        logger.error(f"Integrity error bill update {bill_id}: {e}")
        result = {"success": False, "message": "Update failed. SN conflict?"}
        http_status = 409
    except Exception as e: 
        conn.rollback()
        logger.error(f"Error updating bill {bill_id}: {e}")
        result = {"success": False, "message": f"Error: {str(e)}"}
        http_status = 500
    finally: 
        conn.close()
    return jsonify(result), http_status

@app.route('/api/bills/<int:bill_id>', methods=['DELETE'])
def delete_bill(bill_id):
    """Deletes a specific bill."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM bills WHERE id = ?", (bill_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        conn.commit()
        if conn.total_changes > 0: logger.info(f"Deleted bill ID: {bill_id}"); result, http_status = {"success": True, "message": "Bill deleted"}, 200
        else: logger.warning(f"Delete bill {bill_id} failed."); result, http_status = {"success": False, "message": "Not found"}, 404
    except Exception as e: conn.rollback(); logger.error(f"Error delete bill {bill_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/bills/search', methods=['GET'])
def search_bills():
    """Searches bills based on a term across multiple fields."""
    search_term = request.args.get('term', '').strip(); conn = sqlite3.connect(get_db_path()); search_param = f"%{search_term}%"
    try:
        bills = pd.read_sql_query('''SELECT * FROM bills WHERE serial_number LIKE :term OR customer_name LIKE :term OR mobile_number LIKE :term OR product_size LIKE :term OR current_status LIKE :term OR payment_status LIKE :term ORDER BY id DESC''', conn, params={"term": search_param})
        return jsonify(bills.to_dict('records'))
    except Exception as e: logger.error(f"Error search bills '{search_term}': {e}"); return jsonify({"success": False, "message": "Search error"}), 500
    finally: conn.close()

@app.route('/api/bills/export', methods=['GET'])
def export_bills():
    """Exports all bills to an Excel file."""
    conn = sqlite3.connect(get_db_path()); export_dir = 'exports'
    try: bills = pd.read_sql_query("SELECT * FROM bills ORDER BY id DESC", conn)
    except Exception as e: logger.error(f"Error fetch bills export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir); logger.info(f"Created dir: {export_dir}")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        export_path = os.path.join(base_dir, export_dir, f'bills_export_{timestamp}.xlsx')
        bills.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported bills to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting bills: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500


# Income APIs
@app.route('/api/income', methods=['GET'])
def get_income():
    """Fetches all income records, including payment mode."""
    conn = sqlite3.connect(get_db_path())
    try:
        income = pd.read_sql_query("SELECT id, date, description, amount, payment_mode FROM income ORDER BY date DESC, id DESC", conn)
        return jsonify(income.to_dict('records'))
    except Exception as e: logger.error(f"API Error fetching income: {e}"); return jsonify({"success": False, "message": "Error fetching income"}), 500
    finally: conn.close()

@app.route('/api/income/summary', methods=['GET'])
def get_income_summary():
    """Calculates total income grouped by payment mode."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor(); summary = {}
    try:
        for mode in PAYMENT_MODES: summary[mode] = 0 # Initialize known modes
        cursor.execute("SELECT payment_mode, SUM(amount) FROM income WHERE amount > 0 AND payment_mode IS NOT NULL AND payment_mode != '' GROUP BY payment_mode")
        for row in cursor.fetchall():
            mode, total = row[0], row[1] or 0
            if mode in summary: summary[mode] = total
            else: logger.warning(f"Income summary: Unknown mode {mode}"); summary[mode] = total # Include unknown found modes
        cursor.execute("SELECT SUM(amount) FROM income WHERE amount > 0 AND (payment_mode IS NULL OR payment_mode = '')")
        unspecified_total = cursor.fetchone()[0] or 0
        if unspecified_total > 0: summary['Unspecified'] = unspecified_total
        logger.info(f"Income summary: {summary}")
        return jsonify({"success": True, "summary": summary})
    except Exception as e: logger.error(f"Error calc income summary: {e}"); return jsonify({"success": False, "message": "Error calculating summary"}), 500
    finally: conn.close()

@app.route('/api/income', methods=['POST'])
def add_income():
    """Adds a new income record with payment mode."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None:
         return jsonify({"success": False, "message": "Missing fields"}), 400
    is_valid_mode, mode_error = validate_payment_mode(data.get('payment_mode'), allow_empty=True) # Mode is optional here
    if not is_valid_mode: return jsonify({"success": False, "message": mode_error}), 400
    try: amount = float(data['amount'])
    except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    payment_mode = data.get('payment_mode') or None # Store NULL if empty

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO income (date, description, amount, payment_mode) VALUES (?, ?, ?, ?)', (data['date'], data['description'], amount, payment_mode))
        conn.commit(); logger.info(f"Added income: {data['description']}, Mode: {payment_mode}")
        result, http_status = {"success": True, "message": "Income added"}, 201
    except Exception as e: conn.rollback(); logger.error(f"Error adding income: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/income/<int:income_id>', methods=['PUT'])
def update_income(income_id):
    """Updates an existing income record."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None:
         return jsonify({"success": False, "message": "Missing fields"}), 400
    is_valid_mode, mode_error = validate_payment_mode(data.get('payment_mode'), allow_empty=True)
    if not is_valid_mode: return jsonify({"success": False, "message": mode_error}), 400
    try: amount = float(data['amount'])
    except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    payment_mode = data.get('payment_mode') or None

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM income WHERE id = ?", (income_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute('UPDATE income SET date = ?, description = ?, amount = ?, payment_mode = ? WHERE id = ?', (data['date'], data['description'], amount, payment_mode, income_id))
        conn.commit(); logger.info(f"Updated income ID: {income_id}")
        result, http_status = {"success": True, "message": "Income updated"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error update income {income_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/income/<int:income_id>', methods=['DELETE'])
def delete_income(income_id):
    """Deletes a specific income record."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM income WHERE id = ?", (income_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM income WHERE id = ?", (income_id,))
        conn.commit(); logger.info(f"Deleted income ID: {income_id}")
        result, http_status = {"success": True, "message": "Income deleted"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error delete income {income_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/export/income', methods=['GET'])
def export_income():
    """Exports all income records to an Excel file."""
    conn = sqlite3.connect(get_db_path()); export_dir = 'exports'
    try: income = pd.read_sql_query("SELECT * FROM income ORDER BY date DESC, id DESC", conn)
    except Exception as e: logger.error(f"Error fetch income export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S'); base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        export_path = os.path.join(base_dir, export_dir, f'income_export_{timestamp}.xlsx')
        income.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported income to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting income: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500


# Expense APIs
@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    """Fetches all expense records."""
    conn = sqlite3.connect(get_db_path());
    try: expenses = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC, id DESC", conn); return jsonify(expenses.to_dict('records'))
    except Exception as e: logger.error(f"Error fetch expenses: {e}"); return jsonify({"success": False, "message": "Error fetch"}), 500
    finally: conn.close()

@app.route('/api/expenses', methods=['POST'])
def add_expense():
    """Adds a new expense record."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None: return jsonify({"success": False, "message": "Missing fields"}), 400
    try: amount = float(data['amount']); assert amount >= 0 # Expenses should be non-negative
    except (ValueError, TypeError, AssertionError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO expenses (date, description, amount) VALUES (?, ?, ?)', (data['date'], data['description'], amount))
        conn.commit(); logger.info(f"Added expense: {data['description']}")
        result, http_status = {"success": True, "message": "Expense added"}, 201
    except Exception as e: conn.rollback(); logger.error(f"Error add expense: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/expenses/<int:expense_id>', methods=['PUT'])
def update_expense(expense_id):
    """Updates an existing expense record."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None: return jsonify({"success": False, "message": "Missing fields"}), 400
    try: amount = float(data['amount']); assert amount >= 0
    except (ValueError, TypeError, AssertionError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,));
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute('UPDATE expenses SET date = ?, description = ?, amount = ? WHERE id = ?', (data['date'], data['description'], amount, expense_id))
        conn.commit(); logger.info(f"Updated expense ID: {expense_id}")
        result, http_status = {"success": True, "message": "Expense updated"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error update expense {expense_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    """Deletes a specific expense record."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,));
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit(); logger.info(f"Deleted expense ID: {expense_id}")
        result, http_status = {"success": True, "message": "Expense deleted"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error delete expense {expense_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/export/expenses', methods=['GET'])
def export_expenses():
    """Exports all expense records to an Excel file."""
    conn = sqlite3.connect(get_db_path()); export_dir='exports'
    try: expenses = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC, id DESC", conn)
    except Exception as e: logger.error(f"Error fetch expenses export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S'); base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        export_path = os.path.join(base_dir, export_dir, f'expenses_export_{timestamp}.xlsx')
        expenses.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported expenses to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting expenses: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500


import os
import sys
import sqlite3
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
import pandas as pd
import threading
import logging
import re # Import regex for mobile validation
import signal
import atexit
from werkzeug.serving import make_server

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__, static_folder='static', template_folder='templates')

# --- Configuration ---
PAYMENT_MODES = ["CASH", "ACCOUNT", "UPI", "CARD"]

# --- Database Handling ---
def get_db_path():
    """Determines the correct path for the database file."""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'billing_data.db')

def column_exists(cursor, table_name, column_name):
    """Checks if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [column[1] for column in cursor.fetchall()]
    return column_name in columns

def setup_database():
    """Sets up the database schema, creating tables and altering if necessary."""
    db_path = get_db_path()
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        logger.info(f"Database connected at: {db_path}")

        # --- Schema migration/creation for bills table ---
        cursor.execute("PRAGMA table_info(bills)")
        bills_columns = [column[1] for column in cursor.fetchall()]

        # Rename payment_mode -> advance_payment_mode if necessary
        if 'payment_mode' in bills_columns and 'advance_payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills RENAME COLUMN payment_mode TO advance_payment_mode")
                logger.info("Renamed 'payment_mode' to 'advance_payment_mode' in 'bills' table.")
                bills_columns.remove('payment_mode') # Update local list
                bills_columns.append('advance_payment_mode')
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not rename column 'payment_mode': {e}")

        # Add advance_payment_mode if neither old nor new name exists
        if 'advance_payment_mode' not in bills_columns and 'payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills ADD COLUMN advance_payment_mode TEXT")
                logger.info("Added 'advance_payment_mode' column to 'bills' table.")
                bills_columns.append('advance_payment_mode')
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column 'advance_payment_mode': {e}")

        # Add amount_due_payment_mode if it doesn't exist
        if 'amount_due_payment_mode' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills ADD COLUMN amount_due_payment_mode TEXT")
                logger.info("Added 'amount_due_payment_mode' column to 'bills' table.")
                bills_columns.append('amount_due_payment_mode')
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column 'amount_due_payment_mode': {e}")

        # *** NEW: Add thickness if it doesn't exist ***
        if 'thickness' not in bills_columns:
            try:
                cursor.execute("ALTER TABLE bills ADD COLUMN thickness TEXT")
                logger.info("Added 'thickness' column to 'bills' table.")
                bills_columns.append('thickness')
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column 'thickness': {e}")

        # *** NEW: Add quantity if it doesn't exist ***
        if 'quantity' not in bills_columns:
            try:
                # Default to 1 for existing rows is reasonable
                cursor.execute("ALTER TABLE bills ADD COLUMN quantity INTEGER DEFAULT 1")
                logger.info("Added 'quantity' column to 'bills' table.")
                bills_columns.append('quantity')
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column 'quantity': {e}")


        # Define the final bills table schema (used if table doesn't exist)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            serial_number TEXT UNIQUE NOT NULL,
            customer_name TEXT,
            mobile_number TEXT,
            product_size TEXT,
            thickness TEXT,          -- Added
            quantity INTEGER DEFAULT 1, -- Added
            order_date TEXT,
            delivery_date TEXT,
            current_status TEXT,
            total_price REAL,        -- This is likely price *per unit* now
            advance_payment_mode TEXT,
            advance_amount REAL DEFAULT 0,
            amount_due REAL,
            payment_status TEXT,
            amount_due_payment_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'bills' table schema.")

        # --- Schema migration/creation for income table ---
        # Check if 'income' table exists before trying to alter it
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='income'")
        if cursor.fetchone():
             if not column_exists(cursor, 'income', 'payment_mode'):
                 try:
                     cursor.execute("ALTER TABLE income ADD COLUMN payment_mode TEXT")
                     logger.info("Added 'payment_mode' column to 'income' table.")
                 except sqlite3.OperationalError as e:
                     logger.warning(f"Could not add column 'payment_mode' to 'income': {e}")
        else:
            logger.info("'income' table does not exist yet, will be created.")


        # Define the final income table schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            payment_mode TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'income' table schema.")

        # --- Schema migration/creation for expenses table ---
        cursor.execute("PRAGMA table_info(expenses)")
        expenses_columns = [column[1] for column in cursor.fetchall()]

        # *** NEW: Add quantity to expenses if it doesn't exist ***
        if 'quantity' not in expenses_columns:
            try:
                # Default to 1 for existing rows seems reasonable for expenses too
                cursor.execute("ALTER TABLE expenses ADD COLUMN quantity INTEGER DEFAULT 1")
                logger.info("Added 'quantity' column to 'expenses' table.")
                expenses_columns.append('quantity') # Update local list
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add column 'quantity' to 'expenses': {e}")

        # Define the final expense table schema
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            description TEXT,
            amount REAL,
            quantity INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        logger.info("Checked/Created 'expenses' table schema.")

        conn.commit()
        logger.info("Database setup/migration check completed successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database error during setup: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close(); logger.info("Database connection closed.")

# --- Utility Functions ---
def generate_serial_number():
    """Generates a unique serial number based on date and sequence."""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    date_prefix = datetime.now().strftime('%Y%m%d')
    cursor.execute(
        "SELECT serial_number FROM bills WHERE serial_number LIKE ? ORDER BY serial_number DESC LIMIT 1",
        (f"{date_prefix}%",)
    )
    result = cursor.fetchone()
    counter = 1
    if result:
        try: counter = int(result[0][-3:]) + 1
        except (ValueError, IndexError): logger.warning(f"Could not parse SN counter: {result[0]}")
    new_serial = f"{date_prefix}{counter:03d}"
    conn.close()
    logger.info(f"Generated serial number: {new_serial}")
    return new_serial

# --- Validation Functions ---
def validate_mobile_number(mobile):
    """Validates mobile number format (10 digits, not starting with 0)."""
    if not mobile: return True, None # Allow empty
    pattern = r"^[1-9]\d{9}$"
    if isinstance(mobile, str) and re.fullmatch(pattern, mobile): return True, None
    else: return False, "Mobile number must be exactly 10 digits and cannot start with 0."

def validate_payment_mode(mode, allow_empty=False):
    """Validates payment mode against the allowed list."""
    if not mode and allow_empty: return True, None
    if mode and mode in PAYMENT_MODES: return True, None
    elif not mode and not allow_empty: return False, "Payment mode is required."
    else: return False, f"Invalid Payment Mode. Allowed: {', '.join(PAYMENT_MODES)}."

def validate_amounts(total_price, advance_amount, quantity):
    """Checks if total_price, advance_amount, quantity are valid numbers."""
    try:
        total_p = float(total_price)
        advance_a = float(advance_amount)
        qty = int(quantity)

        if total_p < 0: return False, "Total price cannot be negative."
        if advance_a < 0: return False, "Advance amount cannot be negative."
        if qty <= 0: return False, "Quantity must be a positive integer."
        # Check advance against total cost (price * quantity)
        if advance_a > (total_p * qty): return False, "Advance amount cannot be greater than total cost (Price * Quantity)."

        return True, None
    except (ValueError, TypeError, AttributeError):
        return False, "Invalid number format for Total Price, Advance Amount, or Quantity."

# --- Flask Page Routes ---
@app.route('/')
def index():
    """Renders the main Bills page."""
    return render_template('index.html')

@app.route('/income')
def income_page():
    """Renders the Income page."""
    return render_template('incometbl.html') # Assuming this file exists

@app.route('/expenses')
def expenses_page():
    """Renders the Expenses page."""
    return render_template('expencetbl.html') # Assuming this file exists

@app.route('/stats')
def stats_page():
    """Renders the Statistics page."""
    return render_template('stat.html') # Assuming this file exists

# --- Flask API Routes ---

# Configuration APIs
@app.route('/api/payment-modes', methods=['GET'])
def get_payment_modes():
    """Returns the list of allowed payment modes."""
    return jsonify(PAYMENT_MODES)


# Bill APIs
@app.route('/api/bills', methods=['GET'])
def get_bills():
    """Fetches all bills, ordered by latest first."""
    conn = sqlite3.connect(get_db_path())
    try:
        # SELECT * will now include thickness and quantity
        bills = pd.read_sql_query("SELECT * FROM bills ORDER BY id DESC", conn)
        return jsonify(bills.to_dict('records'))
    except Exception as e:
        logger.error(f"API Error fetching bills: {e}")
        return jsonify({"success": False, "message": "Error fetching bills"}), 500
    finally: conn.close()

@app.route('/api/bills', methods=['POST'])
def add_bill():
    """Adds a new bill with validation and auto-generates serial number."""
    data = request.json
    if not data: return jsonify({"success": False, "message": "Invalid request data"}), 400

    # --- Validation ---
    is_valid_mobile, mobile_error = validate_mobile_number(data.get('mobile_number'))
    if not is_valid_mobile: return jsonify({"success": False, "message": mobile_error}), 400

    # Updated required fields check
    required_fields = ['customer_name', 'order_date', 'delivery_date', 'current_status',
                       'total_price', 'advance_payment_mode', 'payment_status',
                       'product_size', 'thickness', 'quantity'] # Added thickness, quantity
    missing_fields = [field for field in required_fields if data.get(field) is None or data.get(field) == ''] # Check for None or empty string
    if missing_fields: return jsonify({"success": False, "message": f"Missing fields: {', '.join(missing_fields)}"}), 400

    is_valid_adv_mode, adv_mode_error = validate_payment_mode(data.get('advance_payment_mode'), allow_empty=False)
    if not is_valid_adv_mode: return jsonify({"success": False, "message": adv_mode_error}), 400

    # Updated amounts validation
    is_valid_amounts, amount_error = validate_amounts(
        data.get('total_price'),
        data.get('advance_amount', '0'),
        data.get('quantity') # Pass quantity here
    )
    if not is_valid_amounts: return jsonify({"success": False, "message": amount_error}), 400

    # Convert values after validation
    total_price = float(data['total_price'])
    advance_amount = float(data.get('advance_amount', 0))
    quantity = int(data['quantity'])
    advance_payment_mode = data['advance_payment_mode']
    product_size = data.get('product_size')
    thickness = data.get('thickness') # Get thickness

    # --- Logic ---
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    generated_serial_number = generate_serial_number()
    # Calculate amount_due based on quantity
    amount_due = (total_price * quantity) - advance_amount

    try:
        cursor.execute('''
        INSERT INTO bills (serial_number, customer_name, mobile_number, product_size,
                           thickness, quantity,  -- Added columns
                           order_date, delivery_date, current_status, total_price,
                           advance_payment_mode, advance_amount, amount_due, payment_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) -- Added placeholders
        ''', (
            generated_serial_number, data['customer_name'], data.get('mobile_number'),
            product_size, thickness, quantity,  # Added values
            data['order_date'], data['delivery_date'], data['current_status'],
            total_price, advance_payment_mode, advance_amount,
            amount_due, data['payment_status']
            # amount_due_payment_mode is handled during update/payment
        ))
        logger.info(f"Inserted bill SN: {generated_serial_number}")

        # Add advance to income if applicable
        if advance_amount > 0:
            cursor.execute('''
            INSERT INTO income (date, description, amount, payment_mode)
            VALUES (?, ?, ?, ?)
            ''', ( data['order_date'], f"Advance from {data['customer_name']} (SN: {generated_serial_number})", advance_amount, advance_payment_mode ))
            logger.info(f"Added advance income SN: {generated_serial_number}, Mode: {advance_payment_mode}")

        conn.commit()
        result = {"success": True, "message": "Bill added", "serial_number": generated_serial_number}
        http_status = 201
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding bill: {e}")
        result = {"success": False, "message": f"Error: {str(e)}"}
        http_status = 500
    finally:
        conn.close()
    return jsonify(result), http_status


@app.route('/api/bills/<int:bill_id>', methods=['PUT'])
def update_bill(bill_id):
    """Updates an existing bill with validation."""
    data = request.json
    if not data: return jsonify({"success": False, "message": "Invalid request data"}), 400

    # --- Validation ---
    is_valid_mobile, mobile_error = validate_mobile_number(data.get('mobile_number'))
    if not is_valid_mobile: return jsonify({"success": False, "message": mobile_error}), 400

    required_fields = ['serial_number','customer_name', 'order_date', 'delivery_date',
                       'current_status', 'total_price', 'advance_payment_mode',
                       'payment_status', 'product_size', 'thickness', 'quantity'] # Added thickness, quantity
    missing_fields = [field for field in required_fields if data.get(field) is None or data.get(field) == '']
    if missing_fields: return jsonify({"success": False, "message": f"Missing fields: {', '.join(missing_fields)}"}), 400

    is_valid_adv_mode, adv_mode_error = validate_payment_mode(data.get('advance_payment_mode'), allow_empty=False)
    if not is_valid_adv_mode: return jsonify({"success": False, "message": adv_mode_error}), 400

    is_valid_amounts, amount_error = validate_amounts(
        data.get('total_price'),
        data.get('advance_amount', '0'),
        data.get('quantity') # Pass quantity here
    )
    if not is_valid_amounts: return jsonify({"success": False, "message": amount_error}), 400

    # Convert after validation
    total_price = float(data['total_price'])
    advance_amount = float(data.get('advance_amount', 0))
    quantity = int(data['quantity'])
    advance_payment_mode = data['advance_payment_mode']
    payment_status = data['payment_status']
    amount_due_payment_mode = data.get('amount_due_payment_mode') # Get from request
    product_size = data.get('product_size')
    thickness = data.get('thickness') # Get thickness

    # Validate Amount Due Payment Mode *only* if status is PAID and there's a balance due
    new_amount_due = (total_price * quantity) - advance_amount # Calculate potential new due amount
    if payment_status == 'PAID' and new_amount_due > 0: # Check if final payment is needed
         is_valid_due_mode, due_mode_error = validate_payment_mode(amount_due_payment_mode, allow_empty=False) # Must not be empty if paid
         if not is_valid_due_mode:
             return jsonify({"success": False, "message": f"Amount Due Payment Mode Error: {due_mode_error}"}), 400
    elif payment_status == 'PAID' and new_amount_due <= 0: # If overpaid or exactly paid with advance
        amount_due_payment_mode = None # No separate due payment mode needed
    else: # If status is NOT PAID
        amount_due_payment_mode = None # Ensure it's null if not paid

    # --- Logic ---
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get the bill *before* update to check previous status and amount due
    cursor.execute("SELECT payment_status, amount_due, advance_amount, serial_number, customer_name FROM bills WHERE id = ?", (bill_id,))
    current_bill = cursor.fetchone()
    if not current_bill: conn.close(); return jsonify({"success": False, "message": "Bill not found"}), 404

    # Use the newly calculated amount due for the update
    # new_amount_due is already calculated above

    try:
        cursor.execute('''
        UPDATE bills SET
            serial_number = ?, customer_name = ?, mobile_number = ?, product_size = ?,
            thickness = ?, quantity = ?,  -- Added fields
            order_date = ?, delivery_date = ?, current_status = ?, total_price = ?,
            advance_payment_mode = ?, advance_amount = ?, amount_due = ?, payment_status = ?,
            amount_due_payment_mode = ?
        WHERE id = ?
        ''', (
            data['serial_number'], data['customer_name'], data.get('mobile_number'),
            product_size, thickness, quantity,  # Added values
            data['order_date'], data['delivery_date'], data['current_status'],
            total_price, advance_payment_mode, advance_amount,
            new_amount_due, payment_status,
            amount_due_payment_mode, # Save the potentially updated due mode
            bill_id
        ))
        logger.info(f"Updated bill ID: {bill_id}")

        current_payment_status_db = current_bill['payment_status']
        # Use the amount due *before* this update for income recording
        final_payment_amount_db = current_bill['amount_due']

        # Add final payment to income ONLY if status *changes* to PAID and there was an amount due *before* the update
        if payment_status == 'PAID' and current_payment_status_db == 'NOT PAID' and final_payment_amount_db > 0:
            payment_date = datetime.now().strftime('%Y-%m-%d')
            # Use the validated amount_due_payment_mode for the income record
            cursor.execute('''
            INSERT INTO income (date, description, amount, payment_mode)
            VALUES (?, ?, ?, ?)
            ''', ( payment_date, f"Final payment from {data['customer_name']} (SN: {data['serial_number']})", final_payment_amount_db, amount_due_payment_mode ))
            logger.info(f"Added final payment income ID: {bill_id}, Amount: {final_payment_amount_db}, Mode: {amount_due_payment_mode}")

        conn.commit()
        result = {"success": True, "message": "Bill updated"}
        http_status = 200
    except sqlite3.IntegrityError as e:
        conn.rollback()
        logger.error(f"Integrity error bill update {bill_id}: {e}")
        result = {"success": False, "message": "Update failed. Serial number conflict?"}
        http_status = 409
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating bill {bill_id}: {e}")
        result = {"success": False, "message": f"Error: {str(e)}"}
        http_status = 500
    finally:
        conn.close()
    return jsonify(result), http_status

@app.route('/api/bills/<int:bill_id>', methods=['DELETE'])
def delete_bill(bill_id):
    """Deletes a specific bill."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM bills WHERE id = ?", (bill_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        conn.commit()
        if conn.total_changes > 0: logger.info(f"Deleted bill ID: {bill_id}"); result, http_status = {"success": True, "message": "Bill deleted"}, 200
        else: logger.warning(f"Delete bill {bill_id} failed."); result, http_status = {"success": False, "message": "Not found"}, 404
    except Exception as e: conn.rollback(); logger.error(f"Error delete bill {bill_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/bills/search', methods=['GET'])
def search_bills():
    """Searches bills based on a term across multiple fields."""
    search_term = request.args.get('term', '').strip(); conn = sqlite3.connect(get_db_path()); search_param = f"%{search_term}%"
    try:
        # Add thickness to the search query
        query = '''
            SELECT * FROM bills
            WHERE serial_number LIKE :term
               OR customer_name LIKE :term
               OR mobile_number LIKE :term
               OR product_size LIKE :term
               OR thickness LIKE :term      -- Added thickness
               OR current_status LIKE :term
               OR payment_status LIKE :term
            ORDER BY id DESC
        '''
        bills = pd.read_sql_query(query, conn, params={"term": search_param})
        return jsonify(bills.to_dict('records'))
    except Exception as e: logger.error(f"Error search bills '{search_term}': {e}"); return jsonify({"success": False, "message": "Search error"}), 500
    finally: conn.close()

@app.route('/api/bills/export', methods=['GET'])
def export_bills():
    """Exports all bills to an Excel file."""
    conn = sqlite3.connect(get_db_path()); export_dir = 'exports'
    try:
        # SELECT * will now include thickness and quantity
        bills = pd.read_sql_query("SELECT * FROM bills ORDER BY id DESC", conn)
    except Exception as e: logger.error(f"Error fetch bills export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir); logger.info(f"Created dir: {export_dir}")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        # Ensure export_path is correctly constructed
        export_path = os.path.join(base_dir, export_dir, f'bills_export_{timestamp}.xlsx')
        bills.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported bills to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting bills: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500


# --- Income APIs (Keep as is) ---
@app.route('/api/income', methods=['GET'])
def get_income():
    """Fetches all income records, including payment mode."""
    conn = sqlite3.connect(get_db_path())
    try:
        income = pd.read_sql_query("SELECT id, date, description, amount, payment_mode FROM income ORDER BY date DESC, id DESC", conn)
        return jsonify(income.to_dict('records'))
    except Exception as e: logger.error(f"API Error fetching income: {e}"); return jsonify({"success": False, "message": "Error fetching income"}), 500
    finally: conn.close()

@app.route('/api/income/summary', methods=['GET'])
def get_income_summary():
    """Calculates total income grouped by payment mode."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor(); summary = {}
    try:
        for mode in PAYMENT_MODES: summary[mode] = 0 # Initialize known modes
        cursor.execute("SELECT payment_mode, SUM(amount) FROM income WHERE amount > 0 AND payment_mode IS NOT NULL AND payment_mode != '' GROUP BY payment_mode")
        for row in cursor.fetchall():
            mode, total = row[0], row[1] or 0
            if mode in summary: summary[mode] = total
            else: logger.warning(f"Income summary: Unknown mode {mode}"); summary[mode] = total # Include unknown found modes
        cursor.execute("SELECT SUM(amount) FROM income WHERE amount > 0 AND (payment_mode IS NULL OR payment_mode = '')")
        unspecified_total = cursor.fetchone()[0] or 0
        if unspecified_total > 0: summary['Unspecified'] = unspecified_total
        logger.info(f"Income summary: {summary}")
        return jsonify({"success": True, "summary": summary})
    except Exception as e: logger.error(f"Error calc income summary: {e}"); return jsonify({"success": False, "message": "Error calculating summary"}), 500
    finally: conn.close()

@app.route('/api/income', methods=['POST'])
def add_income():
    """Adds a new income record with payment mode."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None:
        return jsonify({"success": False, "message": "Missing fields"}), 400
    is_valid_mode, mode_error = validate_payment_mode(data.get('payment_mode'), allow_empty=True) # Mode is optional here
    if not is_valid_mode: return jsonify({"success": False, "message": mode_error}), 400
    try: amount = float(data['amount'])
    except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    payment_mode = data.get('payment_mode') or None # Store NULL if empty

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO income (date, description, amount, payment_mode) VALUES (?, ?, ?, ?)', (data['date'], data['description'], amount, payment_mode))
        conn.commit(); logger.info(f"Added income: {data['description']}, Mode: {payment_mode}")
        result, http_status = {"success": True, "message": "Income added"}, 201
    except Exception as e: conn.rollback(); logger.error(f"Error adding income: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/income/<int:income_id>', methods=['PUT'])
def update_income(income_id):
    """Updates an existing income record."""
    data = request.json
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None:
        return jsonify({"success": False, "message": "Missing fields"}), 400
    is_valid_mode, mode_error = validate_payment_mode(data.get('payment_mode'), allow_empty=True)
    if not is_valid_mode: return jsonify({"success": False, "message": mode_error}), 400
    try: amount = float(data['amount'])
    except (ValueError, TypeError): return jsonify({"success": False, "message": "Invalid amount"}), 400
    payment_mode = data.get('payment_mode') or None

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM income WHERE id = ?", (income_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute('UPDATE income SET date = ?, description = ?, amount = ?, payment_mode = ? WHERE id = ?', (data['date'], data['description'], amount, payment_mode, income_id))
        conn.commit(); logger.info(f"Updated income ID: {income_id}")
        result, http_status = {"success": True, "message": "Income updated"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error update income {income_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/income/<int:income_id>', methods=['DELETE'])
def delete_income(income_id):
    """Deletes a specific income record."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM income WHERE id = ?", (income_id,))
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM income WHERE id = ?", (income_id,))
        conn.commit(); logger.info(f"Deleted income ID: {income_id}")
        result, http_status = {"success": True, "message": "Income deleted"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error delete income {income_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/export/income', methods=['GET'])
def export_income():
    """Exports all income records to an Excel file."""
    conn = sqlite3.connect(get_db_path()); export_dir = 'exports'
    try: income = pd.read_sql_query("SELECT * FROM income ORDER BY date DESC, id DESC", conn)
    except Exception as e: logger.error(f"Error fetch income export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S'); base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        export_path = os.path.join(base_dir, export_dir, f'income_export_{timestamp}.xlsx')
        income.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported income to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting income: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500


# --- Expense APIs ---
@app.route('/api/expenses', methods=['GET'])
def get_expenses():
    """Fetches all expense records."""
    conn = sqlite3.connect(get_db_path());
    try:
        # SELECT * will now include quantity
        expenses = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC, id DESC", conn)
        return jsonify(expenses.to_dict('records'))
    except Exception as e: logger.error(f"Error fetch expenses: {e}"); return jsonify({"success": False, "message": "Error fetch"}), 500
    finally: conn.close()

@app.route('/api/expenses', methods=['POST'])
def add_expense():
    """Adds a new expense record."""
    data = request.json
    # Check for quantity along with other fields
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None or data.get('quantity') is None:
         return jsonify({"success": False, "message": "Missing required fields (Date, Description, Amount, Quantity)"}), 400

    try:
        amount = float(data['amount'])
        quantity = int(data['quantity']) # Convert quantity to int
        if amount < 0:
             return jsonify({"success": False, "message": "Amount cannot be negative."}), 400
        if quantity <= 0: # Validate quantity is positive
            return jsonify({"success": False, "message": "Quantity must be a positive integer."}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid format for Amount or Quantity."}), 400

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        # Add quantity to the INSERT statement
        cursor.execute('INSERT INTO expenses (date, description, amount, quantity) VALUES (?, ?, ?, ?)',
                       (data['date'], data['description'], amount, quantity))
        conn.commit(); logger.info(f"Added expense: {data['description']} (Qty: {quantity})")
        result, http_status = {"success": True, "message": "Expense added"}, 201
    except Exception as e: conn.rollback(); logger.error(f"Error add expense: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/expenses/<int:expense_id>', methods=['PUT'])
def update_expense(expense_id):
    """Updates an existing expense record."""
    data = request.json
    # Check for quantity along with other fields
    if not data or not data.get('date') or not data.get('description') or data.get('amount') is None or data.get('quantity') is None:
        return jsonify({"success": False, "message": "Missing required fields (Date, Description, Amount, Quantity)"}), 400

    try:
        amount = float(data['amount'])
        quantity = int(data['quantity']) # Convert quantity to int
        if amount < 0:
            return jsonify({"success": False, "message": "Amount cannot be negative."}), 400
        if quantity <= 0: # Validate quantity is positive
            return jsonify({"success": False, "message": "Quantity must be a positive integer."}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid format for Amount or Quantity."}), 400

    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,));
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404

        # Add quantity to the UPDATE statement
        cursor.execute('UPDATE expenses SET date = ?, description = ?, amount = ?, quantity = ? WHERE id = ?',
                       (data['date'], data['description'], amount, quantity, expense_id))
        conn.commit(); logger.info(f"Updated expense ID: {expense_id}")
        result, http_status = {"success": True, "message": "Expense updated"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error update expense {expense_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/expenses/<int:expense_id>', methods=['DELETE'])
def delete_expense(expense_id):
    """Deletes a specific expense record."""
    # This function does not need changes as it operates on ID
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM expenses WHERE id = ?", (expense_id,));
        if not cursor.fetchone(): return jsonify({"success": False, "message": "Not found"}), 404
        cursor.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit(); logger.info(f"Deleted expense ID: {expense_id}")
        result, http_status = {"success": True, "message": "Expense deleted"}, 200
    except Exception as e: conn.rollback(); logger.error(f"Error delete expense {expense_id}: {e}"); result, http_status = {"success": False, "message": str(e)}, 500
    finally: conn.close()
    return jsonify(result), http_status

@app.route('/api/export/expenses', methods=['GET'])
def export_expenses():
    """Exports all expense records to an Excel file."""
    # This function does not need changes as SELECT * and to_excel handle the new column
    conn = sqlite3.connect(get_db_path()); export_dir='exports'
    try: expenses = pd.read_sql_query("SELECT * FROM expenses ORDER BY date DESC, id DESC", conn)
    except Exception as e: logger.error(f"Error fetch expenses export: {e}"); return jsonify({"success": False, "message": "Error fetching data"}), 500
    finally: conn.close()
    try:
        if not os.path.exists(export_dir): os.makedirs(export_dir)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S'); base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        export_path = os.path.join(base_dir, export_dir, f'expenses_export_{timestamp}.xlsx')
        expenses.to_excel(export_path, index=False, engine='openpyxl'); logger.info(f"Exported expenses to: {export_path}")
        return send_file(export_path, as_attachment=True)
    except Exception as e: logger.error(f"Error exporting expenses: {e}"); return jsonify({"success": False, "message": "Error creating file"}), 500

# --- Stats API (Keep as is) ---
@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Calculates and returns key financial statistics."""
    conn = sqlite3.connect(get_db_path()); cursor = conn.cursor()
    try:
        cursor.execute("SELECT SUM(amount) FROM income"); row = cursor.fetchone(); total_income = row[0] if row and row[0] is not None else 0
        cursor.execute("SELECT SUM(amount) FROM expenses"); row = cursor.fetchone(); total_expenses = row[0] if row and row[0] is not None else 0
        cursor.execute("SELECT SUM(amount_due) FROM bills WHERE payment_status = 'NOT PAID'"); row = cursor.fetchone(); pending_payments = row[0] if row and row[0] is not None else 0

        # Initialize monthly data structure for the last 12 months
        months_data = {}
        today = datetime.today()
        for i in range(12):
            current_month = (today.year * 12 + today.month - 1 - i)
            year = current_month // 12
            month = (current_month % 12) + 1
            month_key = f"{year}-{month:02d}"
            months_data[month_key] = {'month': month_key, 'income': 0, 'expenses': 0}

        # Fetch and populate income data
        cursor.execute("SELECT strftime('%Y-%m', date) as month, SUM(amount) as total FROM income WHERE date >= date('now', '-12 months') GROUP BY month")
        for row in cursor.fetchall():
            if row[0] in months_data: months_data[row[0]]['income'] = row[1] or 0

        # Fetch and populate expense data
        cursor.execute("SELECT strftime('%Y-%m', date) as month, SUM(amount) as total FROM expenses WHERE date >= date('now', '-12 months') GROUP BY month")
        for row in cursor.fetchall():
            if row[0] in months_data: months_data[row[0]]['expenses'] = row[1] or 0

        # Sort data chronologically
        sorted_monthly_data = sorted(months_data.values(), key=lambda x: x['month'])

        result = { 'success': True, 'total_income': total_income, 'total_expenses': total_expenses, 'net_profit': total_income - total_expenses, 'pending_payments': pending_payments, 'monthly_data': sorted_monthly_data }; http_status = 200
        logger.info("Calculated stats from DB.")
    except Exception as e:
        logger.error(f"Error calculating stats: {e}")
        result = { 'success': False, 'message': f"Error: {str(e)}", 'total_income': 0, 'total_expenses': 0, 'net_profit': 0, 'pending_payments': 0, 'monthly_data': [] }; http_status = 500
    finally: conn.close()
    return jsonify(result), http_status

# --- Shutdown API & Server Handling (Keep as is) ---
@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Shuts down the application"""
    logger.info("Shutdown requested via API")
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        # Fallback for environments where the function isn't available
        logger.warning("Werkzeug shutdown function not found, forcing exit.")
        atexit._run_exitfuncs() # Try to run registered cleanup functions
        os._exit(0) # Force exit
    try:
        func()
        logger.info("Werkzeug shutdown function called.")
    except Exception as e:
        logger.error(f"Error calling Werkzeug shutdown: {e}. Forcing exit.")
        atexit._run_exitfuncs()
        os._exit(0)
    return jsonify({"success": True, "message": "Server shutting down..."})

class ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        threading.Thread.__init__(self, daemon=True) # Use daemon=True
        self.srv = make_server(host, port, app, threaded=True) # threaded=True might improve responsiveness
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        logger.info("Server thread started.")
        self.srv.serve_forever()
        logger.info("Server thread stopped.") # Will likely only log if shutdown is graceful

    def shutdown(self):
        logger.info("ServerThread shutdown method called.")
        self.srv.shutdown()

# --- App Start ---
server = None # Global variable to hold the server thread instance

def start_browser():
    """Opens the default web browser to the application's URL."""
    import time; time.sleep(1.5) # Allow server time to start
    url = 'http://127.0.0.1:5000'
    logger.info(f"Attempting to open browser at {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        logger.error(f"Could not open browser: {e}")

def cleanup():
    global server
    if server and server.is_alive():
        logger.info("atexit cleanup: Shutting down server...")
        try:
            server.shutdown()
            logger.info("atexit cleanup: Server shutdown complete.")
        except Exception as e:
            logger.error(f"atexit cleanup: Error during server shutdown: {e}")
    else:
         logger.info("atexit cleanup: Server not running or already stopped.")


def main():
    global server
    logger.info("Starting Billing System...")
    setup_database()

    host = '127.0.0.1'
    port = 5000

    # Create the server instance
    server = ServerThread(app, host, port)

    # Register the cleanup function to be called on normal exit and via signal handlers
    atexit.register(cleanup)

    def signal_handler(sig, frame):
        logger.warning(f"Received signal {sig}, initiating shutdown sequence.")
        # cleanup() # atexit should handle this, calling it twice might cause issues
        sys.exit(0) # This will trigger atexit

    # Handle termination signals gracefully
    signal.signal(signal.SIGINT, signal_handler) # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # Kill command

    logger.info(f"Flask server starting at http://{host}:{port}")

    # Start the server thread
    server.start()

    # Open browser only if not in Werkzeug reloader subprocess
    # Check environment variable set by Werkzeug reloader
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not os.environ.get("WERKZEUG_RUN_MAIN"):
         # Start browser slightly delayed in a separate thread to avoid blocking
         browser_thread = threading.Thread(target=start_browser, daemon=True)
         browser_thread.start()


    # Keep the main thread alive. Using server.join() is cleaner than a busy loop.
    try:
        server.join() # Wait indefinitely for the server thread to finish
    except (KeyboardInterrupt, SystemExit):
        logger.info("Main thread interrupted, shutdown should be handled by signal handler/atexit.")
    finally:
        logger.info("Main thread exiting.")


if __name__ == '__main__':
    main()