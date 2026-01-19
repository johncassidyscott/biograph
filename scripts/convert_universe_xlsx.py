#!/usr/bin/env python3
"""
Convert universe Excel file to CSV format for ingestion.
Usage: python convert_universe_xlsx.py input.xlsx output.csv
"""
import sys
import csv

def convert_xlsx_to_csv(xlsx_path: str, csv_path: str):
    """Convert Excel to CSV. Requires openpyxl or pandas."""
    try:
        import pandas as pd
        df = pd.read_excel(xlsx_path)

        # Validate required columns
        required = ['company_name', 'ticker', 'cik']
        missing = [col for col in required if col not in df.columns]
        if missing:
            print(f"Error: Missing required columns: {missing}")
            sys.exit(1)

        # Add defaults if missing
        if 'exchange' not in df.columns:
            df['exchange'] = 'NYSE'
        if 'universe_id' not in df.columns:
            df['universe_id'] = 'xbi'
        if 'start_date' not in df.columns:
            df['start_date'] = '2024-01-01'
        if 'notes' not in df.columns:
            df['notes'] = ''

        # Normalize CIK to 10 digits with leading zeros
        df['cik'] = df['cik'].astype(str).str.zfill(10)

        # Save to CSV
        df.to_csv(csv_path, index=False)
        print(f"✓ Converted {len(df)} companies to {csv_path}")

    except ImportError:
        print("Error: pandas is required. Install with: pip install pandas openpyxl")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_universe_xlsx.py input.xlsx output.csv")
        sys.exit(1)

    convert_xlsx_to_csv(sys.argv[1], sys.argv[2])
