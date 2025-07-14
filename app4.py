import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# --- Page Config ---
st.set_page_config(page_title="DOI Dashboard", layout="wide")
st.title("📦 DOI Dashboard")

# --- File Upload Section ---
st.subheader("Step 1: Upload Files")
sales_file = st.file_uploader("Upload Sales CSV File", type=["csv"])
inventory_file = st.file_uploader("Upload Inventory CSV File", type=["csv"])
po_file = st.file_uploader("Upload PO CSV File", type=["csv"])
fill_rate_file = st.file_uploader("Upload Fill Rate CSV File", type=["csv"])

# --- Days Input ---
st.subheader("Step 2: Enter Number of Days")
x_days = st.number_input("View DOI for past X days", min_value=1, max_value=60, value=7)

# --- Process Button ---
if sales_file and inventory_file and po_file and fill_rate_file and x_days:
    st.success("✅ Files Uploaded. Ready to Process.")

    # Read files
    sales_df = pd.read_csv(sales_file, usecols=["Date", "SKU Number", "SKU Name", "City", "Sales (Qty) - Units"])
    inventory_df = pd.read_csv(inventory_file, usecols=["City", "SKU Name", "SKU Code", "Units"])
    po_df = pd.read_csv(po_file, usecols=['PO No.', 'PO Date', 'Status', 'Del Location', 'SKU', 'SKU Desc', 'Qty', 'GRN Quantity'])
    fill_rate_df = pd.read_csv(fill_rate_file, usecols=["PO Date", "PO Code", "GRN Date", "SKU ID", "SKU Name", "City", "Warehouse Name", "PO Quantity", "GRN Quantity"])

    # Preprocessing fill rate file 

    def po_fill_preprocessing(fill_rate_df, po_df):
        fill_rate_df['PO Date'] = pd.to_datetime(fill_rate_df['PO Date'], format='%d-%m-%Y', errors='coerce').dt.date
        fill_rate_df['GRN Date'] = pd.to_datetime(fill_rate_df['GRN Date'], format='%d-%m-%Y', errors='coerce').dt.date
        fill_rate_df = fill_rate_df[['PO Date','GRN Date', 'PO Code', 'City', 'Warehouse Name', 'SKU ID', 'SKU Name','PO Quantity', 'GRN Quantity']]

        # Preprocessing po file 

        po_df = po_df.rename(columns = {'PO No.' : 'PO Code', 'Del Location' : 'Warehouse Name', 'SKU': 'SKU ID', 'SKU Desc':'SKU Name', 'Qty' : 'PO Quantity'})
        filtered_PO_df = po_df[po_df['Status'].isin(['PENDING_ACKNOWLEDGEMENT', 'PENDING_GRN'])]
        filtered_PO_df['PO Date'] = pd.to_datetime(filtered_PO_df['PO Date'], format='%d %b %Y %I:%M %p')

        filtered_PO_df['PO Date'] = filtered_PO_df['PO Date'].dt.date

        filtered_PO_df = filtered_PO_df[['PO Date', 'PO Code', 'Warehouse Name', 'SKU ID', 'SKU Name', 'PO Quantity', 'GRN Quantity', 'Status']]

        warehouse_to_city = dict(zip(fill_rate_df['Warehouse Name'], fill_rate_df['City']))

        # Step 2: Use the mapping to assign City in filtered_PO_df
        filtered_PO_df['City'] = filtered_PO_df['Warehouse Name'].map(warehouse_to_city)
        filtered_PO_df['GRN Quantity'].fillna(0, inplace = True)
        filtered_PO_df.drop(columns=['SKU Name'], inplace=True)

        # Step 1: Define join keys
        join_keys = ['PO Date', 'PO Code', 'City', 'SKU ID']

        # Step 2: Perform the outer join
        merged_df = pd.merge(
            fill_rate_df,
            filtered_PO_df,
            on=join_keys,
            how='outer',
            suffixes=('_fillrate', '_po')
        )

        # Step 3: Construct final DataFrame with specific columns
        final_df = merged_df[[
            'PO Date',
            'PO Code',
            'City',

            'SKU ID',
            'SKU Name',
            'PO Quantity_fillrate',
            'PO Quantity_po',
            'GRN Quantity_fillrate',
            'GRN Quantity_po',
            'GRN Date',
            'Status'
        ]]

        sku_map = final_df.dropna(subset=['SKU Name']).drop_duplicates(subset=['SKU ID'])[['SKU ID', 'SKU Name']]
        sku_id_to_name = dict(zip(sku_map['SKU ID'], sku_map['SKU Name']))

        # Fill missing SKU Names
        final_df['SKU Name'] = final_df['SKU Name'].fillna(final_df['SKU ID'].map(sku_id_to_name))

        # Combine the quantities (taking sum while treating NaN as 0)
        final_df['PO Quantity'] = final_df[['PO Quantity_fillrate', 'PO Quantity_po']].sum(axis=1, skipna=True)
        final_df['GRN Quantity'] = final_df[['GRN Quantity_fillrate', 'GRN Quantity_po']].sum(axis=1, skipna=True)
        final_df['Status'] = final_df['Status'].fillna('Completed')

        final_df.drop(columns=['PO Quantity_fillrate','PO Quantity_po','GRN Quantity_fillrate','GRN Quantity_po'], inplace=True)

        return final_df

    # --- Preprocessing ---

    sales_df["Date"] = pd.to_datetime(sales_df["Date"], dayfirst=True)

    def filter_sales_last_x_days(sales_df, x_days):
        today = sales_df["Date"].max()
        start_date = today - timedelta(days=x_days - 1)
        return sales_df[sales_df["Date"] >= start_date]

    def group_sales_data(filtered_sales_df):
        return (
            filtered_sales_df
            .groupby(["SKU Number", "SKU Name", "City"], as_index=False)
            .agg({"Sales (Qty) - Units": "sum"})
            .rename(columns={"Sales (Qty) - Units": "Sales Units"})
        )

    def merge_sales_inventory(grouped_sales_df, inventory_df):
        # Create a SKU Number → SKU Name mapping from the sales file
        sales_mapping_df = grouped_sales_df.copy()
        sku_mapping_sales = sales_mapping_df[["SKU Number", "SKU Name"]].drop_duplicates().set_index("SKU Number")["SKU Name"].to_dict()

        inventory_mapping_df = inventory_df.copy()
        inventory_mapping_df.rename(columns = {"SKU Code": "SKU Number"}, inplace = True)
        sku_mapping_inventory = inventory_mapping_df[["SKU Number", "SKU Name"]].drop_duplicates().set_index("SKU Number")["SKU Name"].to_dict()

        # Drop SKU Name from inventory and rename for merging
        inventory_trimmed = inventory_df.drop(columns=["SKU Name"]).rename(
            columns={"SKU Code": "SKU Number", "Units": "Inventory Units"}
        )

        # Merge grouped sales and inventory
        merged_df = pd.merge(
            grouped_sales_df,
            inventory_trimmed,
            on=["City", "SKU Number"],
            how="outer"
        )

        # Fill missing SKU Name using mapping
        merged_df["SKU Name"] = merged_df["SKU Name"].fillna(merged_df["SKU Number"].map(sku_mapping_sales))
        merged_df["SKU Name"] = merged_df["SKU Name"].fillna(merged_df["SKU Number"].map(sku_mapping_inventory))

        # Fill missing sales/inventory units with 0
        merged_df["Sales Units"] = merged_df["Sales Units"].fillna(0)
        merged_df["Inventory Units"] = merged_df["Inventory Units"].fillna(0)

        return merged_df

    # Run pipeline
    filtered_sales = filter_sales_last_x_days(sales_df, x_days)
    grouped_sales = group_sales_data(filtered_sales)
    final_df = merge_sales_inventory(grouped_sales, inventory_df)

    # st.subheader("✅ Preprocessed Data")
    # st.dataframe(final_df, use_container_width=True)


    # --- DOI Calculation ---
    def calculate_doi(df, x_days):
        df["DOI"] = df.apply(
            lambda row: round(row["Inventory Units"] / (row["Sales Units"] / x_days))
            if row["Sales Units"] > 0 else row['Inventory Units'], axis=1
        )
        return df

    st.subheader("📊 View DOI Summary")

    if "pan_india_option" not in st.session_state:
        st.session_state.pan_india_option = "None"
    if "individual_sku" not in st.session_state:
        st.session_state.individual_sku = "None"
    if "individual_city" not in st.session_state:
        st.session_state.individual_city = "None"

    # --- Callback functions to reset others ---
    def set_pan_india():
        st.session_state.individual_sku = "None"
        st.session_state.individual_city = "None"

    def set_individual_sku():
        st.session_state.pan_india_option = "None"
        st.session_state.individual_city = "None"

    def set_individual_city():
        st.session_state.pan_india_option = "None"
        st.session_state.individual_sku = "None"

    # --- Filter Options ---
    col1, col2, col3 = st.columns(3)

    with col1:
        
        st.selectbox(
            "Pan India View",
            options=["None", "Product wise", "City wise"],
            key="pan_india_option",
            on_change=set_pan_india
        )

    with col2:

        sku_list = final_df["SKU Name"].dropna().sort_values().unique()
        st.selectbox(
            "Individual SKU View",
            options=["None"] + list(sku_list),
            key="individual_sku",
            on_change=set_individual_sku
        )

    with col3:

        city_list = final_df["City"].dropna().sort_values().unique()
        st.selectbox(
            "Individual City View",
            options=["None"] + list(city_list),
            key="individual_city",
            on_change=set_individual_city
        )


    # --- Display Logic ---
    if st.session_state.pan_india_option != "None":
        if st.session_state.pan_india_option == "Product wise":
            grouped = final_df.groupby("SKU Name", as_index=False).agg({
                "Sales Units": "sum", "Inventory Units": "sum"
            })
        elif st.session_state.pan_india_option == "City wise":
            grouped = final_df.groupby("City", as_index=False).agg({
                "Sales Units": "sum", "Inventory Units": "sum"
            })
    
        result_df = calculate_doi(grouped, x_days)
        st.write(f"📌 Showing **{st.session_state.pan_india_option}** level DOI summary")
        st.dataframe(result_df, use_container_width=True)
    
    elif st.session_state.individual_sku != "None":
        filtered_sku_df = final_df[final_df["SKU Name"] == st.session_state.individual_sku]
        grouped = filtered_sku_df.groupby(["SKU Name", "City"], as_index=False).agg({
            "Sales Units": "sum", "Inventory Units": "sum"
        })
    
        result_df = calculate_doi(grouped, x_days)
        st.write(f"📌 Showing DOI for **{st.session_state.individual_sku}** across cities")
        st.dataframe(result_df, use_container_width=True)
    
    elif st.session_state.individual_city != "None":
        filtered_city_df = final_df[final_df["City"] == st.session_state.individual_city]
        grouped = filtered_city_df.groupby(["City", "SKU Name"], as_index=False).agg({
            "Sales Units": "sum", "Inventory Units": "sum"
        })

        result_df = calculate_doi(grouped, x_days)
        st.write(f"📌 Showing DOI for **{st.session_state.individual_city}** across all products")
        st.dataframe(result_df, use_container_width=True)


    # --- PO Filters ---
    st.subheader("📦 PO Status Viewer")

    final_po_df = po_fill_preprocessing(fill_rate_df, po_df)
    final_po_df['GRN Date'] = pd.to_datetime(final_po_df['GRN Date'], errors='coerce')
    final_po_df['GRN Date'] = final_po_df['GRN Date'].dt.date

    final_po_df['PO Date'] = pd.to_datetime(final_po_df['PO Date'], errors='coerce')
    final_po_df['PO Date'] = final_po_df['PO Date'].dt.date


    # --- Layout for date range and product selection ---
    col1, col2, col3 = st.columns([1, 1, 1])

    # Default dates
    today = datetime.today().date()
    default_from_date = today - timedelta(days=7)

    # From and To Date Inputs
    with col1:
        from_date = st.date_input("📅 From Date", value=default_from_date, max_value=today)

    with col2:
        to_date = st.date_input("📅 To Date", value=today, min_value=from_date)

    # Filter GRN DataFrame based on selected date range
    filtered_fill_rate_df = final_po_df[(final_po_df['GRN Date'] >= from_date) & (final_po_df['GRN Date'] <= to_date)]

    # Proceed only if filtered GRN data exists
    if not filtered_fill_rate_df.empty:

        # Get product list from PO data
        product_options = filtered_fill_rate_df['SKU Name'].dropna().unique()

        with col3:
            selected_product = st.selectbox("🧃 Select Product", options=sorted(product_options))

        # If product selected, filter and show final data
        if selected_product:
            grn_df = filtered_fill_rate_df[filtered_fill_rate_df['SKU Name'] == selected_product].copy()

            grn_df = grn_df[["SKU Name", "City", "PO Quantity", "GRN Quantity"]]

            # final_df.groupby(["SKU Name"], as_index=False)[["PO Quantity", "GRN Quantity"]].sum()

            grouped_grn_df = grn_df.groupby(['SKU Name','City'], as_index=False)[['PO Quantity', 'GRN Quantity']].sum()

            # st.write(
            #     f"GRN DF"
            # )
            # st.dataframe(
            #     grouped_grn_df,
            #     use_container_width=True
            # )


            open_po_df = final_po_df[final_po_df['GRN Date'].isna()]
            open_po_df = open_po_df[open_po_df['SKU Name'] == selected_product].copy()

            open_po_df = open_po_df.groupby(['City', 'SKU Name'], as_index=False).agg({
                'PO Quantity': 'sum'
            }).rename(columns={'PO Quantity': 'Open PO Quantity'})

            # st.write(
            #     f"PO DF"
            # )
            # st.dataframe(
            #     open_po_df,
            #     use_container_width=True
            # )

            # Outer join
            final_df = pd.merge(grouped_grn_df, open_po_df, on=['City', 'SKU Name'], how='outer')

            final_df[['PO Quantity', 'GRN Quantity', 'Open PO Quantity']] = final_df[[
                'PO Quantity', 'GRN Quantity', 'Open PO Quantity'
            ]].fillna(0)

            # Add GRN Status column
            # grouped_grn_df['GRN Status'] = grouped_grn_df['GRN Quantity'].apply(
            #     lambda x: 'Completed' if pd.notnull(x) and x != 0 else 'Pending'
            # )

            # Display
            st.write(
                f"📌 PO records for **{selected_product}** between **{from_date.strftime('%d %b %Y')}** and **{to_date.strftime('%d %b %Y')}**"
            )
            st.dataframe(
                final_df,
                use_container_width=True
            )

    else:
        st.warning("No GRN data available in the selected date range.")


else:
    st.info("⬆️ Upload all the files and enter number of days to begin.")
