# SlackClone 

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema)
- [Setup and Installation](#setup-and-installation)
- [Running the App](#running-the-app)
- [Usage Guide](#usage-guide)
- [Security](#security)
- [Known Limitations](#known-limitations)

---

## Features

- **User accounts** — register, login, logout, edit profile, change password
- **Workspaces** — create workspaces, invite members, promote admins, remove members
- **Channels** — public, private, and direct message channels
- **Invitations** — invite users to workspaces and private channels, accept or decline
- **Messaging** — post messages, view chronological history, search by keyword
- **Access control** — users only see channels and messages they are authorized to access

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | PostgreSQL |
| DB Connector | psycopg2 |
| Templating | Jinja2 |
| Password Hashing | Werkzeug (pbkdf2:sha256) |
| Session Management | Flask cookie-based sessions |
| Frontend | HTML, CSS |

---

## Project Structure

```
slack-clone/
├── app.py                        # Flask routes and business logic
├── db.py                         # Database connection and query helper
├── requirements.txt              # Python dependencies
├── templates/
│   ├── base.html                 # Shared layout and navbar
│   ├── login.html                # Login page
│   ├── register.html             # Registration page
│   ├── dashboard.html            # Workspaces and invitations overview
│   ├── workspace.html            # Workspace page with channels and members
│   ├── channels.html             # Channel page with messages and search
│   ├── invite_workspace.html     # Invite user to workspace
│   ├── invite_channel.html       # Invite user to private channel
│   ├── change_password.html      # Change password form
│   └── profile.html              # Edit profile form
└── static/
    └── style.css                 # Application styles
```

---

## Database Schema

The database consists of 8 tables:

| Table | Description |
|---|---|
| `users` | Registered user accounts |
| `workspaces` | Workspaces created by users |
| `workspace_members` | M:N relationship — users and workspaces (tracks admin role) |
| `workspace_invitations` | Invitations sent to join a workspace |
| `channels` | Channels within a workspace (public / private / direct) |
| `channel_members` | M:N relationship — users and channels |
| `channel_invitations` | Invitations sent to join a private channel |
| `messages` | Messages posted in channels |

### Key Constraints

- `workspace_members` — composite PK `(workspace_id, user_id)`
- `channel_members` — composite PK `(channel_id, user_id)`
- `channels` — unique constraint on `(workspace_id, name)`
- `workspace_invitations` — partial unique index on `(workspace_id, invited_user_id)` where `status = 'pending'`
- `channel_invitations` — partial unique index on `(channel_id, invited_user_id)` where `status = 'pending'`

---

## Setup and Installation

### Prerequisites

- Python 3.8+
- PostgreSQL 13+
- pip

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/slack-clone.git
cd slack-clone
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt`:
```
flask
psycopg2-binary
werkzeug
markupsafe
```

### 3. Set up PostgreSQL

Open psql and create the database:

```sql
CREATE DATABASE slackclone;
```

Then run the schema:

```sql
CREATE TABLE users (
  user_id       SERIAL PRIMARY KEY,
  email         VARCHAR(255) NOT NULL UNIQUE,
  username      VARCHAR(50)  NOT NULL UNIQUE,
  nickname      VARCHAR(50),
  password_hash VARCHAR(255) NOT NULL,
  created_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE workspaces (
  workspace_id SERIAL PRIMARY KEY,
  name         VARCHAR(100) NOT NULL,
  description  TEXT,
  created_by   INT NOT NULL REFERENCES users(user_id),
  created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE workspace_members (
  workspace_id INT NOT NULL REFERENCES workspaces(workspace_id),
  user_id      INT NOT NULL REFERENCES users(user_id),
  is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
  joined_at    TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE workspace_invitations (
  invitation_id   SERIAL PRIMARY KEY,
  workspace_id    INT NOT NULL REFERENCES workspaces(workspace_id),
  invited_by      INT NOT NULL REFERENCES users(user_id),
  invited_user_id INT NOT NULL REFERENCES users(user_id),
  invited_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  responded_at    TIMESTAMP,
  status          VARCHAR(20) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'accepted', 'declined'))
);

CREATE TABLE channels (
  channel_id   SERIAL PRIMARY KEY,
  workspace_id INT NOT NULL REFERENCES workspaces(workspace_id),
  name         VARCHAR(100) NOT NULL,
  channel_type VARCHAR(10)  NOT NULL
    CHECK (channel_type IN ('public', 'private', 'direct')),
  created_by   INT NOT NULL REFERENCES users(user_id),
  created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
  UNIQUE (workspace_id, name)
);

CREATE TABLE channel_members (
  channel_id INT NOT NULL REFERENCES channels(channel_id),
  user_id    INT NOT NULL REFERENCES users(user_id),
  joined_at  TIMESTAMP NOT NULL DEFAULT NOW(),
  PRIMARY KEY (channel_id, user_id)
);

CREATE TABLE channel_invitations (
  invitation_id   SERIAL PRIMARY KEY,
  channel_id      INT NOT NULL REFERENCES channels(channel_id),
  invited_by      INT NOT NULL REFERENCES users(user_id),
  invited_user_id INT NOT NULL REFERENCES users(user_id),
  invited_at      TIMESTAMP NOT NULL DEFAULT NOW(),
  responded_at    TIMESTAMP,
  status          VARCHAR(20) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'accepted', 'declined'))
);

CREATE TABLE messages (
  message_id SERIAL PRIMARY KEY,
  channel_id INT  NOT NULL REFERENCES channels(channel_id),
  user_id    INT  NOT NULL REFERENCES users(user_id),
  body       TEXT NOT NULL,
  posted_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Partial unique indexes to prevent duplicate pending invitations
CREATE UNIQUE INDEX one_pending_per_workspace
ON workspace_invitations (workspace_id, invited_user_id)
WHERE status = 'pending';

CREATE UNIQUE INDEX one_pending_per_channel
ON channel_invitations (channel_id, invited_user_id)
WHERE status = 'pending';
```

### 4. Configure the database connection

Edit `db.py` with your PostgreSQL credentials:

```python
def get_connection():
    return psycopg2.connect(
        host="localhost",
        database="postgres",   # change if needed
        user="postgres",       # your postgres username
        password="yourpassword"  # your postgres password
    )
```

### 5. Set a secret key

In `app.py`, change:

```python
app.secret_key = 'your_secret_key_change_this'
```

To any long random string:

```python
app.secret_key = 'xK9#mP2$qL7nR4@wZ1vB8'
```

---

## Running the App

```bash
python app.py
```

Then open your browser and go to:

```
http://localhost:5000
```

> ⚠️ Always use `http://` not `https://` — the development server does not support TLS.

---

## Usage Guide

### Register and Login
1. Go to `http://localhost:5000/register`
2. Enter email, username, optional nickname, and password
3. Click **Create Account** → redirected to login
4. Enter username and password → click **Login**

### Create a Workspace
1. On the dashboard, enter a workspace name and description
2. Click **Create** — you are automatically set as admin

### Invite a User to a Workspace
1. Go to your workspace (admins only)
2. Click **Invite User**
3. Enter the username → click **Send Invitation**
4. The invitee sees the invitation on their dashboard and can Accept or Decline

### Create a Channel
1. Go to your workspace
2. Enter a channel name, select type (Public / Private)
3. Click **Create**

### Direct Message
1. On the workspace page, enter a username in the **Direct Message** section
2. Click **Start DM** — a private channel is created between you and that user

### Post a Message
1. Click on a channel name
2. Type your message in the text box
3. Click **Send**

### Search Messages
1. Open a channel
2. Type a keyword in the search box
3. Click **Search** — only messages you have access to are returned

### Manage Members (Admins only)
- **Make Admin** — promotes a member to administrator
- **Remove** — removes a member from the workspace and all its channels

---

## UI Features

### Light / Dark Mode
The application supports both light and dark themes. 
Users can toggle between modes using the button in the 
navbar. The preference is saved so it persists across 
page navigation.

## Security

### SQL Injection Prevention
All queries use psycopg2 parameterized statements. User input is
never concatenated into SQL strings directly:

```python
# Safe — parameterized
db.query("SELECT * FROM users WHERE username=%s", (username,))
```

### XSS Prevention
Jinja2 automatically escapes all `{{ variable }}` output,
preventing injected scripts from executing in the browser.

### Password Security
Passwords are hashed using `werkzeug.security` with
`pbkdf2:sha256`. Plaintext passwords are never stored.

### Session Management
User identity is stored in a signed Flask session cookie.
Every protected route verifies `user_id` is present in the
session before processing.

### Concurrency
Multi-step operations use explicit transactions with
`conn.commit()` and `conn.rollback()` to ensure atomicity
under concurrent use.

### Access Control
All content restrictions are enforced at the application level.
Users can only see channels they are members of, and only
messages in channels they belong to within workspaces they
have joined.

---

## Known Limitations

- Plain text messages only — images and rich text not supported
  (excluded by project specification)
- Message and channel deletion not supported
  (excluded by project specification)
- No real-time updates — page must be refreshed to see new messages
- No threading within channels — messages are a flat sequence
- Development server only — not suitable for production deployment

---
