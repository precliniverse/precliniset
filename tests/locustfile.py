from locust import HttpUser, between, task


class WebsiteUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        """Login on start"""
        # You should create a test user in your DB for this
        self.client.post("/auth/login", data={
            "email": "admin@example.com", 
            "password": "password"
        })

    @task(2)
    def index(self):
        self.client.get("/")

    @task(1)
    def projects(self):
        self.client.get("/projects/")

    @task(1)
    def dashboard(self):
        self.client.get("/main/dashboard")
