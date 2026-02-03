
import unittest
from app import create_app, db
from app.models import User, ExperimentalGroup, Animal, DataTable, ProtocolModel, Analyte, AnalyteDataType
from datetime import date, datetime, timezone

class TestDataTableRegressions(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        
        self.client = self.app.test_client()
        
        # Create user
        user = User(email='test@example.com', is_active=True, email_confirmed=True)
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        
        self.client.post('/auth/login', data={'email': 'test@example.com', 'password': 'password'})

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_datatable_view_columns_and_id(self):
        # Setup Data
        protocol = ProtocolModel(name="Test Protocol")
        analyte = Analyte(name="Weight", data_type=AnalyteDataType.FLOAT)
        protocol.analytes.append(analyte)
        db.session.add(protocol)
        
        group = ExperimentalGroup(name="Test Group", team_id=1, owner_id=1)
        db.session.add(group)
        db.session.flush()
        
        animal = Animal(
            uid="A001", 
            group_id=group.id, 
            date_of_birth=date(2023, 1, 1),
            measurements={"Weight": 100},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.session.add(animal)
        
        dt = DataTable(
            group_id=group.id,
            protocol_id=protocol.id,
            date="2024-01-01",
            name="Test Table"
        )
        db.session.add(dt)
        db.session.commit()
        
        dt_id = dt.id

        # Test View Page
        response = self.client.get(f'/datatables/view/{dt_id}')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        
        # CHECK 1: Columns
        self.assertIn('Weight', html, "Analyte 'Weight' should be visible")
        
        # CHECK 2: ID Display
        self.assertIn("A001", html, "Animal UID 'A001' should be visible")

if __name__ == '__main__':
    unittest.main()
