# Divided project into modules:
 - [ ] 1. Register and Login
    a. Register with email, hash password + salt and store in database
    b. Support password login and onetime password
    c. Generate token bind with current login session, supports log out and expires.

 - [ ] 2. Identity key management for users
    a. Store private key in device, public in server
    b. Display the public key finger print of contacts, allows user to mark them as "verified"
    c. If the session token of contact changed, warn users about it and decides whether to let it pass

 - [ ] 3. E2E encryption message
    a. establish private connection between two users
    b. Apply authentication encryption such as AEAD to each message
    c. Somehow make sure that message isn't tampered with when sent
    d. Making sure there is no replay attack

 - [ ] 4. Contact management
    a. Send, receive and accept friend request
    b. Block and unblock
    c. default message limit to one

 - [ ] 5. Offline Messages
    a. Show two status for sent message: delivered, unreceived
    b. Offline deliver queue
    c. delete if waiting too long
 - [ ] 6. Self destruction Message
    a. A mechanism on client side that deletes message after certain period of time.

 - [ ] 7. CLI or UI
    a. Whatever the fuck


# Database:

Store on Server side:

Table User:
    UUID                             PK
    Email                            Att (Unique)
    User Name                        Att
    Password Hash                    Att
    Public keys                      Att

Table Devices:
    DeviceID                         PK
    User UUID                        FK (ref User.UUID)
    Device Hash                      Att
    Device public key                Att

Table Friendship:
    Relation_id                      PK
    user_id                          FK (ref User.UUID)
    user_id                          FK (ref User.UUID)
    Status                           Att 

Table Friend Request
    Request ID                       PK
    Sender                           FK (ref User.UUID)
    Receiver                         FK (ref User.UUID)
    Status                           Att 
    Expire Duration                  Att

Table Offline Message
    Message ID                       PK
    Sender UUID                      FK (ref User.UUID)
    Receiver UUID                    FK (ref User.UUID)
    Ciphertext                       Att 
    Expire Duration                  Att 

Store on Client Side:

Table Local Identity:
    UUID                             PK 
    Public_key                       Att
    Private_key                      Att

Table Conversation:
    Contact UUID                     PK 
    Contact Name                     Att
    Unread Threads                   Att

Table Contact Devices:
    Contact Device ID                PK
    Contact UUID                     FK (Ref Conversation.Contact UUID)
    Public Key                       Att
    Is Verified                      Att    

Table Message:
    Message ID                       PK
    Conversation ID                  FK (References Conversation.Contact UUID)
    Sender ID                        Att
    Receiver ID                      Att
    Content Plaintext                Att
    Expire Duration                  Att
    Receive At                       Att


# API First Coding & Async Coding
This project uses API First design, where the communication streams between server and client are predefined————before either server or client is written. It use *pydantic* and *FastAPI* together to achieve low cost, efficient communication between server and client.
*pydantic* is use to predefine the communication protocol between client and server, as well as offers a input validation against malicious request. 
*FastAPI* is used to handle input and output validation to make program faster. FastAPI also provides a websocket functionality so that we can save much time in managing websockets.


Instead of multi-threading, this project uses asynchronus libraries to handle multiple inputs. Python's base design made it horrible in multithread performance, so asyn coding is a better choice.


# Python Decorators
Evil motherfuckers. 
Modern Python code implements lots of "declarative coding" and "meta coding". @ is used to convert functions into library specific functions with registered functionalities. It saves us time from manually register each function after we wrote them.

# About @contextmanager and yield
伟大，无需多言。

