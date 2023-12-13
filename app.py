from fastapi import FastAPI, Form, HTTPException
from fastapi_sso.sso.google import GoogleSSO
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Annotated, Union
import requests
import uvicorn
import httpx
import os
import json

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

with open('1.json', 'r') as file:
    data = json.load(file)
data = data['web']

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
CLIENT_ID = data.get("client_id")
CLIENT_SECRET = data.get("client_secret")
# OAUTH_URL = data.get("auth_uri")
OAUTH_URL = "http://localhost:5001"

sso = GoogleSSO(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    # redirect_uri=OAUTH_URL + "/auth/callback",
    redirect_uri="http://localhost:5001/auth/callback",
    # redirect_uri="http://your_ec2_instance.com/auth/callback",
    allow_insecure_http=True,

)

# to get a string like this run:
# openssl rand -hex 32
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict, expires_delta: Union[timedelta, None] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_google_userinfo(access_token: str):
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://www.googleapis.com/oauth2/v2/userinfo',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        response.raise_for_status()
        return response.json()

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse("index.html",
                                      {"request": request,
                                                "login_form_action": f"{OAUTH_URL}/auth/login",})


@app.get("/auth/login")
async def login():
    with sso:
        return await sso.get_login_redirect(params={"prompt": "consent",
                                                    "access_type": "offline",})

@app.get("/auth/callback")
async def auth_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Exchange the code for a token
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": "http://localhost:5001/auth/callback",
        "grant_type": "authorization_code"
    }
    token_response = requests.post(token_url, data=token_data)
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    # id_token = token_json.get("id_token")

    user_info = await get_google_userinfo(access_token)
    # Check or register for Identity

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_info["email"]}, expires_delta=access_token_expires
    )

    api_gateway_url = "https://m1ydupxwfa.execute-api.us-east-2.amazonaws.com/deploy"
    # access_token = access_token.strip("'")
    print(access_token)
    headers = {
        "access_token": access_token,
        "token_type": "bearer"
    }

    response = requests.post(api_gateway_url, headers = headers)

    # Check if the Lambda function returned a redirect response
    if response.status_code == 200:
        # Extract the redirect URL from the Lambda function's response headers
        response_json = response.json()

        status_code = response_json['statusCode']

        if status_code == 403:
            return {'statusCode': 403, 'body': json.dumps('User not authorized')}

        redirect_url = response_json["headers"]["Location"]

        if redirect_url:
            # Perform the redirection
            return RedirectResponse(url=redirect_url)
        else:
            # Handle the case where the redirect URL is not provided
            return {"error": "No redirect URL provided by the Lambda function"}
    else:
        # Handle other responses (e.g., error scenarios)
        return {"error": "Unexpected response from the API gateway", "status_code": response.status_code}




if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5001)

