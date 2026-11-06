CREATE DATABASE IF NOT EXISTS banksight_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE banksight_db;

CREATE TABLE IF NOT EXISTS customers (
  customer_id INT AUTO_INCREMENT PRIMARY KEY,
  display_name VARCHAR(100) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_customers_display_name (display_name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS accounts (
  account_id INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  account_type ENUM('Savings', 'Current', 'Fixed Deposit') NOT NULL,
  opening_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
  current_balance DECIMAL(15,2) NOT NULL DEFAULT 0.00,
  status ENUM('Active', 'Inactive') NOT NULL DEFAULT 'Active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_accounts_customer (customer_id),
  CONSTRAINT fk_accounts_customer FOREIGN KEY (customer_id)
    REFERENCES customers(customer_id) ON DELETE RESTRICT,
  CONSTRAINT ck_accounts_opening_balance CHECK (opening_balance >= 0),
  CONSTRAINT ck_accounts_current_balance CHECK (current_balance >= 0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS transactions (
  transaction_id INT AUTO_INCREMENT PRIMARY KEY,
  account_id INT NOT NULL,
  transaction_date DATETIME NOT NULL,
  transaction_type ENUM('Deposit', 'Withdrawal') NOT NULL,
  amount DECIMAL(15,2) NOT NULL,
  description VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_transactions_account (account_id),
  INDEX idx_transactions_date (transaction_date),
  INDEX idx_transactions_type (transaction_type),
  CONSTRAINT fk_transactions_account FOREIGN KEY (account_id)
    REFERENCES accounts(account_id) ON DELETE RESTRICT,
  CONSTRAINT ck_transactions_amount CHECK (amount > 0)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS review_flags (
  review_id INT AUTO_INCREMENT PRIMARY KEY,
  transaction_id INT NOT NULL,
  rule_name VARCHAR(80) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  review_status ENUM('Pending', 'Reviewed', 'Dismissed') NOT NULL DEFAULT 'Pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME NULL,
  UNIQUE KEY uq_review_transaction_rule (transaction_id, rule_name),
  INDEX idx_review_status (review_status),
  CONSTRAINT fk_review_transaction FOREIGN KEY (transaction_id)
    REFERENCES transactions(transaction_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS app_settings (
  setting_key VARCHAR(80) PRIMARY KEY,
  setting_value VARCHAR(255) NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

