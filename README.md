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

Table Login_Information:
    Email                            PK
    UUID                             FK
    User Name                        FK
    Password Hash                    Att
    Public keys                      Att

Table User:
    UUID                             PK
    Devices                          FK
    User Name                        Att
    Opt_token                        Att
    Friends                          Att
    Friend Request Received          Att
    Friend Request Sent              Att

Table Devices:
    DeviceID                         PK
    UUID                             FK
    Device Hash                      Att
    Device public key                Att
    Is Verified                      Att

Table Friendship:
    Relation_id                      PK
    user_id                          FK
    user_id                          FK

Table Friend Request
    Request ID                       PK
    Sender                           FK
    Receiver                         FK
    Status                           Att
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
    Messages                         Att

Table Message:
    Message ID                       PK
    Conversation ID                  FK
    Sender ID                        Att
    Receiver ID                      Att
    Content Plaintext                Att
    Expire Duration                  Att