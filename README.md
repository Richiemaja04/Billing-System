# Billing and Income/Expense Tracker

A simple web-based application built with Flask to manage customer bills, track income, and record expenses. It uses a local SQLite database to store data and provides functionalities to add, update, delete, search, and export records.

## Features

* **Bill Management:**
    * Add new customer bills with details like name, mobile, product size, thickness, quantity, order/delivery dates, status, price, and advance payment.
    * Automatically generates unique serial numbers for bills.
    * Update existing bill details.
    * Track payment status (PAID/NOT PAID) and record payment modes for advance and final payments.
    * Delete bills.
    * Search bills by various fields (Serial No, Name, Mobile, Size, Thickness, Status).
    * Export all bills to an Excel file (`.xlsx`).
* **Income Tracking:**
    * Record income entries with date, description, amount, and payment mode.
    * Update and delete income records.
    * View income summary grouped by payment mode.
    * Export all income records to an Excel file (`.xlsx`).
* **Expense Tracking:**
    * Record expense entries with date, description, amount, and quantity.
    * Update and delete expense records.
    * Export all expense records to an Excel file (`.xlsx`).
* **Statistics:**
    * View overall statistics including total income, total expenses, net profit, and total pending payments from unpaid bills.
    * See a monthly breakdown of income vs. expenses for the last 12 months.
* **Web Interface:** Simple HTML interface to interact with the application features.
* **Database:** Uses SQLite for data persistence (`billing_data.db`).

## File Structure



## Technologies Used

* **Backend:** Python, Flask
* **Database:** SQLite3
* **Data Handling:** Pandas (for export)
* **Frontend:** HTML, (Likely CSS and JavaScript in the `static` folder)

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <your-repository-directory>
    ```
2.  **Install dependencies:**
    It's recommended to use a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
    You'll need to create a `requirements.txt` file based on the imports in `main.py`. A basic one might look like this:
    ```txt
    # requirements.txt
    Flask
    pandas
    openpyxl # Needed by pandas to write .xlsx files
    Werkzeug # Usually installed with Flask
    ```
    Then install them:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Run the application:**
    ```bash
    python main.py
    ```
    This will start the Flask development server, typically on `http://127.0.0.1:5000`.

## Usage

1.  Run the application using `python main.py`.
2.  The script should automatically open the application in your default web browser. If not, navigate to `http://127.0.0.1:5000`.
3.  Use the navigation links or buttons to access the Bills, Income, Expenses, and Stats sections.
4.  Use the forms and tables provided on each page to manage your data.
