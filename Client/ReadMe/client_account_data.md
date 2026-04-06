Terminal A:

cd /Users/tj/Downloads/project/COMP3334
export CLIENT_STATE_PATH=/tmp/client-a-state.json
export CLIENT_DB_PATH=/tmp/client-a.db
python3 -m Client.main register --email alice@example.com --user-name alice --password password123
python3 -m Client.main login --email alice@example.com --password password123 --otp-code 123456



Registered user UUID: 281f5ca3-a6a5-472c-9a4e-fcb54a078c33
OTP secret: ULB4PRI22FBDAPUU3IGF34T22MQODHWM
Store the OTP secret in your authenticator app before logging in.

Terminal B:

cd /Users/tj/Downloads/project/COMP3334
export CLIENT_STATE_PATH=/tmp/client-b-state.json
export CLIENT_DB_PATH=/tmp/client-b.db
python3 -m Client.main register --email bob@example.com --user-name bob --password password123
python3 -m Client.main login --email bob@example.com --password password123 --otp-code 123456

Registered user UUID: 9e1f6783-cfc6-4a05-a851-64f83e3f7183
OTP secret: K6HC3OURWW67YIEWOZTRDYCISO6DNLMI
Store the OTP secret in your authenticator app before logging in.