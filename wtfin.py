import pandas as pd

# Historical Data for WTF (in millions)
data = {
    'Fiscal Year': [2022, 2023, 2024, 2025, 2026, 2027],
    'Revenue': [3931, 3504, 3355, 6000, 6600, 7260],
    'Gross Profit': [938, 806, 753, 850, 1056, 1306],
    'Gross Margin (%)': [23.9, 23.0, 22.4, 14.17, 16.0, 18.0],
    'SG&A': [689, 638, 640, 1080, 1100, 1150],
    'Operating Income': [244, 161, 107, -230, -44, 156],
    'Operating Margin (%)': [6.2, 4.6, 3.2, -3.8, -0.7, 2.1]
}

# Convert to DataFrame
financial_df = pd.DataFrame(data)

# Export the DataFrame to Excel
financial_df.to_excel("WTF_Financial_Model.xlsx", index=False)

print("Excel file 'WTF_Financial_Model.xlsx' has been created.")
