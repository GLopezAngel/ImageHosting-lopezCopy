How to deploy:

Launch an EC2 Instance

Create an S3 Bucket
Allow Public Access
Add CORS policy to S3 Bucket

[
    {
        "AllowedHeaders": [
            "*"
        ],
        "AllowedMethods": [
            "GET",
            "PUT",
            "POST"
        ],
        "AllowedOrigins": [
            "http://{YOUR_EC2_IP}:8000",
            "http://localhost:8000"
        ],
        "ExposeHeaders": []
    }
]

Connect to the EC2 Instance
Install pip and git
Clone the Repository
Create a Virtual Environment 
Install the requirements
Start the redis6 server
Start the app.py
