import pandas as pd
import io

def export_to_csv(report):
    rows = []
    
    # Process MySQL drifts
    for db_name, drifts in report.get('mysql', {}).items():
        for drift in drifts:
            rows.append({
                "Severity": drift['severity'],
                "Database": db_name,
                "Object Type": drift['type'].split('_')[-1], # e.g. TABLE, COLUMN
                "Object Name": drift['object'],
                "Drift Type": drift['type'],
                "Details": drift['detail']
            })
            
    # Process Mongo drifts
    for db_name, drifts in report.get('mongo', {}).items():
        for drift in drifts:
            rows.append({
                "Severity": drift['severity'],
                "Database": db_name,
                "Object Type": drift['type'].split('_')[-1],
                "Object Name": drift['object'],
                "Drift Type": drift['type'],
                "Details": drift['detail']
            })
            
    if not rows:
        # Return empty CSV with headers
        df = pd.DataFrame(columns=["Severity", "Database", "Object Type", "Object Name", "Drift Type", "Details"])
    else:
        df = pd.DataFrame(rows)
        
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    return csv_buffer.getvalue()
