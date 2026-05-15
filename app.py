from flask import Flask, render_template, request, redirect, url_for, session, flash
from markupsafe import escape
from werkzeug.security import generate_password_hash, check_password_hash
import db

app = Flask(__name__)
app.secret_key = 'your_secret_key_change_this'

# ─────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    User registeration 
    Check 1. No duplicate email and username
    
    Queried table : User
    Affected Table : user """
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        username = request.form.get('username', '').strip()
        nickname = request.form.get('nickname', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not username or not password:
            flash('Email, username and password are required.')
            return render_template('register.html')

        # Check email separately
        existing_email = db.query(
            "SELECT user_id FROM users WHERE email=%s",
            (email,), fetchone=True
        )
        if existing_email:
            flash('Email already registered.')
            return render_template('register.html')

        # Check username separately
        existing_username = db.query(
            "SELECT user_id FROM users WHERE username=%s",
            (username,), fetchone=True
        )
        if existing_username:
            flash('Username already taken.')
            return render_template('register.html')

        password_hash = generate_password_hash(password, method="pbkdf2:sha256")

        db.query(
            """INSERT INTO users (email, username, nickname, password_hash)
               VALUES (%s, %s, %s, %s)""",
            (email, username, nickname, password_hash)
        )
        flash('Account created! Please log in.')
        return redirect(url_for('login'))

    return render_template('register.html')



@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login checks for valid username and password
    
    Queried tables : user
    Affected Table : None
    """
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        user = db.query(
            "SELECT * FROM users WHERE username=%s",
            (username,), fetchone=True
        )

        if not user or not check_password_hash(user['password_hash'], password):
            flash('Invalid username or password.')
            return render_template('login.html')

        # Store user in session cookie
        session['user_id']  = user['user_id']
        session['username'] = user['username']
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─────────────────────────────────────────
# DASHBOARD — list workspaces
# ─────────────────────────────────────────

@app.route('/dashboard')
def dashboard():
    """
    Show workspace part of, pending invitation for both workspace and channels

    Queriesd tables : Workspace, channels, workspace_invitation, channel_invitation
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    workspaces = db.query(
        """SELECT w.workspace_id, w.name, w.description, wm.is_admin
           FROM workspaces w
           JOIN workspace_members wm ON w.workspace_id = wm.workspace_id
           WHERE wm.user_id = %s
           ORDER BY w.name""",
        (user_id,)
    )

    # Pending workspace invitations
    workspace_invitations = db.query(
        """SELECT wi.invitation_id, w.name AS workspace_name, u.username AS invited_by
           FROM workspace_invitations wi
           JOIN workspaces w ON wi.workspace_id = w.workspace_id
           JOIN users u ON wi.invited_by = u.user_id
           WHERE wi.invited_user_id = %s AND wi.status = 'pending'""",
        (user_id,)
    )

    # Pending channel invitations
    channel_invitations = db.query(
        """SELECT ci.invitation_id, c.name AS channel_name, w.name AS workspace_name, u.username AS invited_by
           FROM channel_invitations ci
           JOIN channels c ON ci.channel_id = c.channel_id
           JOIN workspaces w ON c.workspace_id = w.workspace_id
           JOIN users u ON ci.invited_by = u.user_id
           WHERE ci.invited_user_id = %s AND ci.status = 'pending'""",
        (user_id,)
    )

    return render_template('dashboard.html',workspaces=workspaces, invitations=workspace_invitations, channel_invitations=channel_invitations)


@app.route('/workspace/create', methods=['POST'])
def create_workspace():
    """
    Create workspaces feature
    
    Affected tables : workspace, workspace_members"""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    user_id = session['user_id']

    if not name:
        flash('Workspace name is required.')
        return redirect(url_for('dashboard'))

    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Transaction: create workspace + add creator as admin
        cur.execute(
            """INSERT INTO workspaces (name, description, created_by)
               VALUES (%s, %s, %s) RETURNING workspace_id""",
            (name, description, user_id)
        )
        workspace_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO workspace_members 
               (workspace_id, user_id, is_admin)
               VALUES (%s, %s, TRUE)""",
            (workspace_id, user_id)
        )
        conn.commit()
        flash(f'Workspace "{name}" created.')
    except Exception as e:
        conn.rollback()
        flash('Error creating workspace.')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))


@app.route('/invitation/<int:inv_id>/respond', methods=['POST'])
def respond_workspace_invitation(inv_id):
    """
    Queried tables : workspace_invitation
    Affected tables : Workspace_inviations, workspace_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    action  = request.form.get('action')  # 'accepted' or 'declined'
    user_id = session['user_id']

    if action not in ('accepted', 'declined'):
        flash('Invalid action.')
        return redirect(url_for('dashboard'))

    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Verify invitation belongs to this user
        cur.execute(
            """SELECT workspace_id FROM workspace_invitations
               WHERE invitation_id=%s AND invited_user_id=%s
               AND status='pending'""",
            (inv_id, user_id)
        )
        inv = cur.fetchone()
        if not inv:
            flash('Invitation not found.')
            conn.close()
            return redirect(url_for('dashboard'))

        workspace_id = inv[0]

        # Update invitation status
        cur.execute(
            """UPDATE workspace_invitations SET status=%s, responded_at=NOW() WHERE invitation_id=%s""",
            (action, inv_id)
        )

        # If accepted, add to workspace_members
        if action == 'accepted':
            cur.execute(
                """INSERT INTO workspace_members 
                   (workspace_id, user_id, is_admin)
                   VALUES (%s, %s, FALSE)
                   ON CONFLICT DO NOTHING""",
                (workspace_id, user_id)
            )
        conn.commit()
        flash(f'Invitation {action}.')
    
    except Exception as e:
        conn.rollback()
        flash('Error responding to invitation.')
    
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────
# WORKSPACE — list channels, invite users
# ─────────────────────────────────────────

@app.route('/workspace/<int:workspace_id>')
def workspace(workspace_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    
    # print(f"DEBUG: user_id={user_id}, workspace_id={workspace_id}")

    # Check user is a member
    member = db.query(
        """SELECT is_admin FROM workspace_members
           WHERE workspace_id=%s AND user_id=%s""",
        (workspace_id, user_id), fetchone=True
    )

    # print(f"DEBUG: member={member}")
    
    if not member:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    workspace_info = db.query(
        "SELECT * FROM workspaces WHERE workspace_id=%s",
        (workspace_id,), fetchone=True
    )
    
    # Public channels + channels user is a member of
    channels = db.query(
        """SELECT c.channel_id, c.name, c.channel_type,
                EXISTS(
                SELECT 1 FROM channel_members cm
                WHERE cm.channel_id = c.channel_id
                AND cm.user_id = %s
                ) AS is_member
           FROM channels c
           WHERE c.workspace_id = %s
             AND (c.channel_type = 'public'
               OR EXISTS(
                    SELECT 1 FROM channel_members cm
                    WHERE cm.channel_id = c.channel_id
                    AND cm.user_id = %s))
           ORDER BY c.channel_type, c.name""",
        (user_id, workspace_id, user_id)
    )
    # print(f"DEBUG: channels={channels}")
    members = db.query(
    """SELECT u.user_id, u.username, wm.is_admin
       FROM workspace_members wm
       JOIN users u ON wm.user_id = u.user_id
       WHERE wm.workspace_id=%s
       ORDER BY wm.is_admin DESC, u.username""",
    (workspace_id,) )

    return render_template('workspace.html',workspace=workspace_info, channels=channels,members=members, is_admin=member['is_admin'])
    

@app.route('/workspace/<int:workspace_id>/channel/create', methods=['POST'])
def create_channel(workspace_id):
    """
    Create a new channel inside a workspace.
    Checks user is a workspace member before creating.
    Creator is automatically added as channel member.

    Queried tables: workspace_members
    Affected tables: channels, channel_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    name = request.form.get('name', '').strip()
    channel_type = request.form.get('channel_type', 'public')

    if channel_type not in ('public', 'private', 'direct'):
        flash('Invalid channel type.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Check user is workspace member
        cur.execute(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id=%s AND user_id=%s""",
            (workspace_id, user_id)
        )
        if not cur.fetchone():
            flash('Not authorized.')
            return redirect(url_for('dashboard'))

        # Create channel + add creator as member (transaction)
        cur.execute(
            """INSERT INTO channels 
               (workspace_id, name, channel_type, created_by)
               VALUES (%s, %s, %s, %s) RETURNING channel_id""",
            (workspace_id, name, channel_type, user_id)
        )
        channel_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO channel_members (channel_id, user_id)
               VALUES (%s, %s)""",
            (channel_id, user_id)
        )
        conn.commit()
        flash(f'Channel #{name} created.')
    except Exception as e:
        conn.rollback()
        flash('Channel name may already exist in this workspace.')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('workspace', workspace_id=workspace_id))

@app.route('/workspace/<int:workspace_id>/remove/<int:target_user_id>', methods=['POST'])
def remove_workspace_member(workspace_id, target_user_id):
    """Removing an user from workspace
    1. Check if user exists in workspace
    2. Admin initiates the request
    3. Remove user from all channels in that workspace
    
    Queried tables : workspace_members
    Affected table : workspace_members, channel_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Only admins can remove
    admin = db.query(
        """SELECT 1 FROM workspace_members
           WHERE workspace_id=%s AND user_id=%s 
           AND is_admin=TRUE""",
        (workspace_id, user_id), fetchone=True
    )
    if not admin:
        flash('Only admins can remove members.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    # Can't remove yourself
    if target_user_id == user_id:
        flash('You cannot remove yourself.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    # Remove from workspace and all its channels
    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Remove from all channels in this workspace first
        cur.execute(
            """DELETE FROM channel_members
               WHERE user_id=%s
                 AND channel_id IN (
                   SELECT channel_id FROM channels
                   WHERE workspace_id=%s
                 )""",
            (target_user_id, workspace_id)
        )
        # Remove from workspace
        cur.execute(
            """DELETE FROM workspace_members
               WHERE workspace_id=%s AND user_id=%s""",
            (workspace_id, target_user_id)
        )
        conn.commit()
        flash('Member removed.')
    except Exception as e:
        conn.rollback()
        flash('Error removing member.')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('workspace', workspace_id=workspace_id))

@app.route('/workspace/<int:workspace_id>/promote/<int:target_user_id>', methods=['POST'])
def promote_to_admin(workspace_id, target_user_id):
    """ 
    Promoting user to admin 
    Queried tables : workspace_members
    Affected tables : workspace_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Only admins can promote
    admin = db.query(
        """SELECT 1 FROM workspace_members
           WHERE workspace_id=%s AND user_id=%s 
           AND is_admin=TRUE""",
        (workspace_id, user_id), fetchone=True
    )
    if not admin:
        flash('Only admins can promote members.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    db.query(
        """UPDATE workspace_members SET is_admin=TRUE
           WHERE workspace_id=%s AND user_id=%s""",
        (workspace_id, target_user_id)
    )
    flash('Member promoted to admin.')
    return redirect(url_for('workspace', workspace_id=workspace_id))


@app.route('/workspace/<int:workspace_id>/direct', methods=['POST'])
def create_direct_channel(workspace_id):
    """
    Creating Direct Channels 
    1. Check if invited user exists
    2. Check if invited user is in the workspace
    3. Check if a direct channel already exists between them or not
    4. User cannot send direct channel invitation to themselves 

    Queried Tables :  Users, Workspace_members, channel, channel_members
    Affected : channel, channel_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    target_username = request.form.get('username', '').strip()

    # Find target user
    target = db.query(
        "SELECT user_id, username FROM users WHERE username=%s",
        (target_username,), fetchone=True
    )
    if not target:
        flash(f'User "{target_username}" not found.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    target_id = target['user_id']

    if target_id == user_id:
        flash('You cannot start a direct message with yourself.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    # Check target is in same workspace
    in_workspace = db.query(
        """SELECT 1 FROM workspace_members
           WHERE workspace_id=%s AND user_id=%s""",
        (workspace_id, target_id), fetchone=True
    )
    if not in_workspace:
        flash('That user is not in this workspace.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    # Check if direct channel already exists between these two
    existing = db.query(
        """SELECT c.channel_id FROM channels c
           JOIN channel_members cm1 
             ON c.channel_id = cm1.channel_id AND cm1.user_id=%s
           JOIN channel_members cm2 
             ON c.channel_id = cm2.channel_id AND cm2.user_id=%s
           WHERE c.workspace_id=%s 
             AND c.channel_type='direct'""",
        (user_id, target_id, workspace_id), fetchone=True
    )
    if existing:
        # Already exists, just go there
        return redirect(url_for('channel', channel_id=existing['channel_id']))

    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Create direct channel named after both users
        channel_name = f"{session['username']}-{target['username']}"
        cur.execute(
            """INSERT INTO channels 
               (workspace_id, name, channel_type, created_by)
               VALUES (%s, %s, 'direct', %s)
               RETURNING channel_id""",
            (workspace_id, channel_name, user_id)
        )
        channel_id = cur.fetchone()[0]

        # Add both users
        cur.execute(
            """INSERT INTO channel_members (channel_id, user_id)
               VALUES (%s, %s), (%s, %s)""",
            (channel_id, user_id, channel_id, target_id)
        )
        conn.commit()
        return redirect(url_for('channel', channel_id=channel_id))
    except Exception as e:
        conn.rollback()
        flash('Error creating direct message.')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('workspace', workspace_id=workspace_id))

@app.route('/workspace/<int:workspace_id>/invite', methods=['GET', 'POST'])
def invite_to_workspace(workspace_id):
    """
    Send invitations to a workspace
    Check: 1. Admin sends the invite
    2. Invitee must exists
    3. Invitee must be a member already
    4. No duplicate invitations
    
    Queried tables : workspace_members, workspaces, workspace_invitation 
    Affected Table : workspace_invitations
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # check if admin is the sending invite
    member = db.query( """SELECT is_admin FROM workspace_members WHERE workspace_id=%s AND user_id=%s""", (workspace_id, user_id), fetchone=True )
    
    if not member or not member['is_admin']:
        flash('Only admins can invite users.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    workspace_info = db.query(
        "SELECT * FROM workspaces WHERE workspace_id=%s",
        (workspace_id,), fetchone=True
    )

    if request.method == 'POST':
        invitee_username = request.form.get('username', '').strip()

        invitee = db.query(
            "SELECT user_id FROM users WHERE username=%s",
            (invitee_username,), fetchone=True
        )
        
        if not invitee:
            flash(f'User "{invitee_username}" not found.')
            return render_template('invite_workspace.html', workspace=workspace_info)

        invitee_id = invitee['user_id']

        if invitee_id == user_id: # No self invites
            flash('You cannot invite yourself.')
            return render_template('invite_workspace.html', workspace=workspace_info)

        # Check if already a member
        already_member = db.query(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id=%s AND user_id=%s""",
            (workspace_id, invitee_id), fetchone=True
        )
        if already_member:
            flash(f'{invitee_username} is already a member.')
            return render_template('invite_workspace.html', workspace=workspace_info)

        # Check if already has a pending invitation
        already_invited = db.query(
            """SELECT 1 FROM workspace_invitations
               WHERE workspace_id=%s 
                 AND invited_user_id=%s 
                 AND status='pending'""",
            (workspace_id, invitee_id), fetchone=True
        )
        if already_invited:
            flash(f'{invitee_username} already has a pending invitation.')
            return render_template('invite_workspace.html', workspace=workspace_info)

        # Send invitation
        db.query(
            """INSERT INTO workspace_invitations
               (workspace_id, invited_by, invited_user_id, status)
               VALUES (%s, %s, %s, 'pending')""",
            (workspace_id, user_id, invitee_id)
        )
        flash(f'Invitation sent to {invitee_username}.')
        return redirect(url_for('workspace', workspace_id=workspace_id))

    return render_template('invite_workspace.html', workspace=workspace_info)


# ─────────────────────────────────────────
# CHANNEL — messages, post, search
# ─────────────────────────────────────────

@app.route('/channel/<int:channel_id>')
def channel(channel_id):
    """
    Channel information and message filtering using keyword 
    
    Queried tables : Workspaces, Workspace_members, Channel_members, Messages
    Affected tables : None
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    keyword = request.args.get('search', '').strip()

    # Verify access: must be workspace member + channel member
    access = db.query(
        """SELECT 1 FROM channel_members cm
           JOIN channels c ON cm.channel_id = c.channel_id
           JOIN workspace_members wm 
             ON c.workspace_id = wm.workspace_id
           WHERE cm.channel_id=%s 
             AND cm.user_id=%s 
             AND wm.user_id=%s""",
        (channel_id, user_id, user_id), fetchone=True
    )
    if not access:
        flash('Access denied.')
        return redirect(url_for('dashboard'))

    channel_info = db.query(
        """SELECT c.*, w.name AS workspace_name, w.workspace_id
           FROM channels c
           JOIN workspaces w ON c.workspace_id = w.workspace_id
           WHERE c.channel_id=%s""",
        (channel_id,), fetchone=True
    )

    # Messages — optionally filtered by keyword
    if keyword:
        messages = db.query(
            """SELECT m.*, u.username
               FROM messages m
               JOIN users u ON m.user_id = u.user_id
               WHERE m.channel_id=%s 
                 AND m.body LIKE %s
               ORDER BY m.posted_at ASC""",
            (channel_id, f'%{keyword}%')
        )
    else:
        messages = db.query(
            """SELECT m.*, u.username
               FROM messages m
               JOIN users u ON m.user_id = u.user_id
               WHERE m.channel_id=%s
               ORDER BY m.posted_at ASC""",
            (channel_id,)
        )

    return render_template('channels.html', channel=channel_info, messages=messages, keyword=keyword)


@app.route('/channel/<int:channel_id>/post', methods=['POST'])
def post_message(channel_id):
    """
    Send message on channel
    Check if user is part of channel

    Queried tables : Channel_members

    Affected tables :  Messages
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    body    = request.form.get('body', '').strip()

    if not body:
        return redirect(url_for('channel', channel_id=channel_id))

    # Verify membership before posting
    member = db.query(
        """SELECT 1 FROM channel_members
           WHERE channel_id=%s AND user_id=%s""",
        (channel_id, user_id), fetchone=True
    )
    if not member:
        flash('You are not a member of this channel.')
        return redirect(url_for('dashboard'))

    db.query(
        """INSERT INTO messages (channel_id, user_id, body)
           VALUES (%s, %s, %s)""",
        (channel_id, user_id, body)
    )
    return redirect(url_for('channel', channel_id=channel_id))

@app.route('/channel/<int:channel_id>/invite', methods=['GET', 'POST'])
def invite_to_channel(channel_id):
    """
    Send channel invitation to a user 
    1. Invitee must be workspace member
    2. Invitor cannot invite themselves
    3. Invitee must exists
    4. No duplicate invitations
    5. Invitee should not be part of channel

    Queried tables : Workspaces, Channels, Workspace_members, Channel_invitations, Channel_members

    Affected tables : Channel_invitations
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Get channel info
    channel_info = db.query(
        """SELECT c.*, w.workspace_id 
           FROM channels c
           JOIN workspaces w ON c.workspace_id = w.workspace_id
           WHERE c.channel_id = %s""",
        (channel_id,), fetchone=True
    )

    if not channel_info:
        flash('Channel not found.')
        return redirect(url_for('dashboard'))

    # Only creator of private channel can invite
    if channel_info['channel_type'] == 'private' and \
       channel_info['created_by'] != user_id:
        flash('Only the channel creator can invite to private channels.')
        return redirect(url_for('channel', channel_id=channel_id))

    # User must be a channel member to invite
    is_member = db.query(
        """SELECT 1 FROM channel_members
           WHERE channel_id=%s AND user_id=%s""",
        (channel_id, user_id), fetchone=True
    )
    if not is_member:
        flash('You are not a member of this channel.')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        invitee_username = request.form.get('username', '').strip()

        # Find user by username
        invitee = db.query(
            "SELECT user_id FROM users WHERE username=%s",
            (invitee_username,), fetchone=True
        )
        if not invitee:
            flash(f'User "{invitee_username}" not found.')
            return render_template('invite_channel.html', channel=channel_info)

        invitee_id = invitee['user_id']

        # Can't invite yourself
        if invitee_id == user_id:
            flash('You cannot invite yourself.')
            return render_template('invite_channel.html', channel=channel_info)

        # Invitee must be a workspace member first
        in_workspace = db.query(
            """SELECT 1 FROM workspace_members
               WHERE workspace_id=%s AND user_id=%s""",
            (channel_info['workspace_id'], invitee_id), fetchone=True
        )
        if not in_workspace:
            flash(f'{invitee_username} is not a member of this workspace.')
            return render_template('invite_channel.html', channel=channel_info)

        # Check if already a channel member
        already_member = db.query(
            """SELECT 1 FROM channel_members
               WHERE channel_id=%s AND user_id=%s""",
            (channel_id, invitee_id), fetchone=True
        )
        if already_member:
            flash(f'{invitee_username} is already in this channel.')
            return render_template('invite_channel.html', channel=channel_info)

        # Check if already has pending invitation
        already_invited = db.query(
            """SELECT 1 FROM channel_invitations
               WHERE channel_id=%s 
                 AND invited_user_id=%s 
                 AND status='pending'""",
            (channel_id, invitee_id), fetchone=True
        )
        if already_invited:
            flash(f'{invitee_username} already has a pending invitation.')
            return render_template('invite_channel.html', channel=channel_info)

        # Send invitation
        db.query(
            """INSERT INTO channel_invitations
               (channel_id, invited_by, invited_user_id, status)
               VALUES (%s, %s, %s, 'pending')""",
            (channel_id, user_id, invitee_id)
        )
        flash(f'Invitation sent to {invitee_username}.')
        return redirect(url_for('channel', channel_id=channel_id))

    return render_template('invite_channel.html', channel=channel_info)

@app.route('/channel-invitation/<int:inv_id>/respond', methods=['POST'])
def respond_channel_invitation(inv_id):
    """Response to an invitation
    1. Check if invitation exists
    2. If accepted, add user to channel_members 
    Affected tables : channel_invitation, channel_members 
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    action  = request.form.get('action')

    if action not in ('accepted', 'declined'):
        flash('Invalid action.')
        return redirect(url_for('dashboard'))

    conn = db.get_connection()
    cur  = conn.cursor()
    try:
        # Verify invitation belongs to this user
        cur.execute(
            """SELECT channel_id FROM channel_invitations
               WHERE invitation_id=%s 
                 AND invited_user_id=%s
                 AND status='pending'""",
            (inv_id, user_id)
        )
        inv = cur.fetchone()
        if not inv:
            flash('Invitation not found.')
            conn.close()
            return redirect(url_for('dashboard'))

        channel_id = inv[0]

        # Update invitation status
        cur.execute(
            """UPDATE channel_invitations
               SET status=%s, responded_at=NOW()
               WHERE invitation_id=%s""",
            (action, inv_id)
        )

        # If accepted add to channel_members
        if action == 'accepted':
            cur.execute(
                """INSERT INTO channel_members (channel_id, user_id)
                   VALUES (%s, %s)
                   ON CONFLICT DO NOTHING""",
                (channel_id, user_id)
            )
        conn.commit()
        flash(f'Invitation {action}.')
    except Exception as e:
        conn.rollback()
        flash('Error responding to invitation.')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('dashboard'))

@app.route('/channel/<int:channel_id>/join', methods=['POST'])
def join_channel(channel_id):
    """
    Join a public channel directly without invitation.
    Only public channels can be joined this way.

    Queried tables: channels
    Affected tables: channel_members
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    # Only allow joining public channels directly
    ch = db.query(
        "SELECT * FROM channels WHERE channel_id=%s",
        (channel_id,), fetchone=True
    )
    if not ch or ch['channel_type'] != 'public':
        flash('You can only join public channels directly.')
        return redirect(url_for('dashboard'))

    db.query(
        """INSERT INTO channel_members (channel_id, user_id)
           VALUES (%s, %s) ON CONFLICT DO NOTHING""",
        (channel_id, user_id)
    )
    return redirect(url_for('channel', channel_id=channel_id))

# ─────────────────────────────────────────
# CHANGE PASSWORD
# ─────────────────────────────────────────


@app.route('/change-password', methods=['GET', 'POST'])
def change_password():
    """
    Change user
    Queried Table : User
    Altered Table : User
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        current_password = request.form.get('current_password', '').strip()
        new_password     = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        # Check all fields filled
        if not current_password or not new_password or not confirm_password:
            flash('All fields are required.')
            return render_template('change_password.html')

        # Check new passwords match
        if new_password != confirm_password:
            flash('New passwords do not match.')
            return render_template('change_password.html')

        # Check minimum length
        if len(new_password) < 6:
            flash('New password must be at least 6 characters.')
            return render_template('change_password.html')

        # Fetch current hash from database
        user = db.query(
            "SELECT password_hash FROM users WHERE user_id=%s",
            (user_id,), fetchone=True
        )

        # Verify current password is correct
        if not check_password_hash(user['password_hash'], current_password):
            flash('Current password is incorrect.')
            return render_template('change_password.html')

        # Hash new password and update
        new_hash = generate_password_hash(new_password, method="pbkdf2:sha256")
        db.query(
            "UPDATE users SET password_hash=%s WHERE user_id=%s",
            (new_hash, user_id)
        )

        flash('Password changed successfully.')
        return redirect(url_for('dashboard'))

    return render_template('change_password.html')


# ─────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
def edit_profile(): 
    """
    Edit profile attributes (username/email)

    Queried Tables : User
    Altered Tables : User
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user    = db.query(
        "SELECT * FROM users WHERE user_id=%s",
        (user_id,), fetchone=True
    )

    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        username = request.form.get('username', '').strip()

        if not username:
            flash('Username cannot be empty.')
            return render_template('profile.html', user=user)

        # Check username not taken by someone else
        taken = db.query(
            """SELECT user_id FROM users 
               WHERE username=%s AND user_id != %s""",
            (username, user_id), fetchone=True
        )
        if taken:
            flash('Username already taken.')
            return render_template('profile.html', user=user)

        db.query(
            """UPDATE users SET username=%s, nickname=%s
               WHERE user_id=%s""",
            (username, nickname, user_id)
        )
        session['username'] = username
        flash('Profile updated.')
        return redirect(url_for('dashboard'))

    return render_template('profile.html', user=user)
if __name__ == '__main__':
    app.run(debug=True)