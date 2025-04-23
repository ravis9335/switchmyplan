import pandas as pd
import psycopg2
import os
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.tree import DecisionTreeClassifier

# Function to Extract Data from PostgreSQL
def extract_data_from_db():
    conn = psycopg2.connect(
        dbname="mark1_db",
        user="mark1_user",
        password="securepassword",
        host="localhost",
        port="5432"
    )
    query = "SELECT carrier, plan_name, data_amount, price, plan_code FROM plans"
    df = pd.read_sql(query, conn)
    conn.close()
    csv_file_path = "plans_data.csv"
    df.to_csv(csv_file_path, index=False)
    print(f"CSV file created at {csv_file_path}")
    return df

# Ensure CSV File Exists
csv_file_path = "plans_data.csv"

if not os.path.exists(csv_file_path):
    print("CSV file not found. Extracting data from the database...")
    df = extract_data_from_db()
else:
    print("CSV file found. Proceeding with loading data.")
    df = pd.read_csv(csv_file_path)

# Encode Categorical Variables
encoder = LabelEncoder()
df['carrier_encoded'] = encoder.fit_transform(df['carrier'])

# Define Features and Target
X = df[['data_amount', 'price', 'carrier_encoded']]
y = df['plan_name']

# Split Data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train Model
model = DecisionTreeClassifier()
model.fit(X_train, y_train)

print("Decision Tree Model Trained Successfully!")