import pytest
import pandas as pd
from app.models import Animal, ExperimentalGroup, DataTable, ProtocolModel, Analyte, AnalyteDataType, ProtocolAnalyteAssociation, ExperimentDataRow
from app.services.analysis_service import AnalysisService

def test_hybrid_dataframe_construction(test_app, db_session):
    """
    Verify that AnalysisService correctly extracts JSON data from SQL
    and merges it into a Pandas DataFrame with correct types.
    """
    with test_app.app_context():
        # 1. Setup Infrastructure
        model_name = f"Hybrid Test Model {id(db_session)}"
        group = ExperimentalGroup(id="GRP-HYBRID", name="Hybrid Group", project_id=1, team_id=1, owner_id=1, model_id=1)
        db_session.add(group)
        db_session.flush()

        # 2. Create Protocol with 1 Numeric and 1 Categorical Analyte
        a_weight = Analyte(name="Weight_Hybrid", data_type=AnalyteDataType.FLOAT)
        a_color = Analyte(name="Color_Hybrid", data_type=AnalyteDataType.CATEGORY)
        db_session.add_all([a_weight, a_color])
        db_session.flush()

        protocol = ProtocolModel(name="Hybrid Protocol")
        db_session.add(protocol)
        db_session.flush()
        
        db_session.add(ProtocolAnalyteAssociation(protocol_model_id=protocol.id, analyte_id=a_weight.id))
        db_session.add(ProtocolAnalyteAssociation(protocol_model_id=protocol.id, analyte_id=a_color.id))

        # 3. Create DataTable
        dt = DataTable(group_id=group.id, protocol_id=protocol.id, date="2024-01-01")
        db_session.add(dt)
        db_session.flush()

        # 4. Insert Hybrid Data (SQL Animal + JSON Row Data)
        # Animal 1: Has data
        a1 = Animal(uid="A1-H", display_id="A1", group_id=group.id, status='alive')
        db_session.add(a1)
        db_session.flush()
        
        # Row Data (JSON) - Note: Mixed types in JSON
        row_data = {
            "Weight_Hybrid": 25.5,    # Float
            "Color_Hybrid": "Black"   # String
        }
        db_session.add(ExperimentDataRow(data_table_id=dt.id, animal_id=a1.id, row_data=row_data))

        # Animal 2: No data (Should appear with NaNs)
        a2 = Animal(uid="A2-H", display_id="A2", group_id=group.id, status='alive')
        db_session.add(a2)
        
        db_session.commit()

        # 5. EXECUTE SERVICE
        service = AnalysisService()
        df, num_cols, cat_cols = service.prepare_dataframe(dt)

        # 6. ASSERTIONS
        assert df is not None, "DataFrame should not be None"
        assert len(df) == 2, "Should have 2 rows (one per animal)"
        
        # Check Columns
        assert 'Weight_Hybrid' in df.columns
        assert 'Color_Hybrid' in df.columns
        assert 'uid' in df.columns
        assert 'id' not in num_cols, "Internal ID should not be in numerical columns"

        # Check Values & Types
        # A1
        row_a1 = df[df['uid'] == 'A1-H'].iloc[0]
        assert row_a1['Weight_Hybrid'] == 25.5
        assert row_a1['Color_Hybrid'] == "Black"
        assert isinstance(row_a1['Weight_Hybrid'], float)

        # A2
        row_a2 = df[df['uid'] == 'A2-H'].iloc[0]
        assert pd.isna(row_a2['Weight_Hybrid']), "Missing numeric data should be NaN"
        assert row_a2['Color_Hybrid'] is None or pd.isna(row_a2['Color_Hybrid'])

        # Check Categorization
        assert 'Weight_Hybrid' in num_cols
        assert 'Color_Hybrid' in cat_cols

        print("\n✅ Hybrid SQL/JSON extraction verified successfully.")