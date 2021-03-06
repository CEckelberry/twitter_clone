import os

from flask import Flask, render_template, request, flash, redirect, session, g
from flask_debugtoolbar import DebugToolbarExtension
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from forms import UserAddForm, LoginForm, MessageForm, EditUserForm
from models import db, connect_db, User, Message, Likes

CURR_USER_KEY = "curr_user"

app = Flask(__name__)

# Get DB_URI from environ variable (useful for production/testing) or,
# if not set there, use development local db.
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "postgres:///warbler"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ECHO"] = False
app.config["DEBUG_TB_INTERCEPT_REDIRECTS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "it's a secret")
toolbar = DebugToolbarExtension(app)

connect_db(app)

##############################################################################
# User signup/login/logout


@app.before_request
def add_user_to_g():
    """If we're logged in, add curr user to Flask global."""

    if CURR_USER_KEY in session:
        g.user = User.query.get(session[CURR_USER_KEY])

    else:
        g.user = None


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Logout user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Handle user signup.

    Create new user and add to DB. Redirect to home page.

    If form not valid, present form.

    If the there already is a user with that username: flash message
    and re-present form.
    """

    form = UserAddForm()

    if form.validate_on_submit():
        try:
            user = User.signup(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
                image_url=form.image_url.data or User.image_url.default.arg,
            )
            db.session.commit()

        except IntegrityError:
            flash("Username already taken", "danger")
            return render_template("users/signup.html", form=form)

        do_login(user)

        return redirect("/")

    else:
        return render_template("users/signup.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            do_login(user)
            flash(f"Hello, {user.username}!", "success")
            return redirect("/")

        flash("Invalid credentials.", "danger")

    return render_template("users/login.html", form=form)


@app.route("/logout")
def logout():
    """Handle logout of user."""

    session.clear()
    flash("You have logged out successfully!", "success")
    return redirect("/login")


##############################################################################
# General user routes:


@app.route("/users")
def list_users():
    """Page with listing of users.

    Can take a 'q' param in querystring to search by that username.
    """

    search = request.args.get("q")

    if not search:
        users = User.query.all()
    else:
        users = User.query.filter(User.username.like(f"%{search}%")).all()

    return render_template("users/index.html", users=users)


@app.route("/users/<int:user_id>")
def users_show(user_id):
    """Show user profile."""

    user = User.query.get_or_404(user_id)

    # snagging messages in order from the database;
    # user.messages won't be in order by default
    messages = (
        Message.query.filter(Message.user_id == user_id)
        .order_by(Message.timestamp.desc())
        .limit(100)
        .all()
    )

    likes = Likes.query.filter_by(user_id=user_id).count()

    print(likes)

    return render_template("users/show.html", user=user, messages=messages, likes=likes)


@app.route("/users/<int:user_id>/following")
def show_following(user_id):
    """Show list of people this user is following."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template("users/following.html", user=user)


@app.route("/users/<int:user_id>/followers")
def users_followers(user_id):
    """Show list of followers of this user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template("users/followers.html", user=user)


@app.route("/users/follow/<int:follow_id>", methods=["POST"])
def add_follow(follow_id):
    """Add a follow for the currently-logged-in user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    followed_user = User.query.get_or_404(follow_id)
    g.user.following.append(followed_user)
    db.session.commit()

    return redirect(f"/users/{g.user.id}/following")


@app.route("/users/stop-following/<int:follow_id>", methods=["POST"])
def stop_following(follow_id):
    """Have currently-logged-in-user stop following this user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    followed_user = User.query.get(follow_id)
    g.user.following.remove(followed_user)
    db.session.commit()

    return redirect(f"/users/{g.user.id}/following")


@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def profile(user_id):
    """Update profile for current user."""

    user = User.query.get_or_404(user_id)
    form = EditUserForm(obj=user)

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    if form.validate_on_submit():
        user.username = form.username.data
        user.email = form.email.data
        user.image_url = form.image_url.data
        user.header_image_url = form.header_image_url.data
        user.bio = form.bio.data
        user.location = form.location.data
        password = g.user.password

        user_auth = User.authenticate(form.username.data, form.password.data)

        if user_auth:
            try:
                db.session.commit()
                return redirect(f"/users/{g.user.id}")
            except SQLAlchemyError as e:
                print(str(e))
                db.session.rollback()
                raise
                return redirect(f"/users/{g.user.id}")
        else:
            flash("Incorrect Username/Password.", "danger")
            return redirect("/")

    return render_template("/users/edit.html", form=form, user=user)


@app.route("/users/delete", methods=["POST"])
def delete_user():
    """Delete user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    do_logout()

    db.session.delete(g.user)
    db.session.commit()

    return redirect("/signup")


##############################################################################
# Messages routes:


@app.route("/messages/new", methods=["GET", "POST"])
def messages_add():
    """Add a message:

    Show form if GET. If valid, update message and redirect to user page.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = MessageForm()

    if form.validate_on_submit():
        msg = Message(text=form.text.data)
        g.user.messages.append(msg)
        db.session.commit()

        return redirect(f"/users/{g.user.id}")

    return render_template("messages/new.html", form=form)


@app.route("/messages/<int:message_id>", methods=["GET"])
def messages_show(message_id):
    """Show a message."""

    msg = Message.query.get(message_id)
    return render_template("messages/show.html", message=msg)


@app.route("/messages/<int:message_id>/delete", methods=["POST"])
def messages_destroy(message_id):
    """Delete a message."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    msg = Message.query.get(message_id)
    db.session.delete(msg)
    db.session.commit()

    return redirect(f"/users/{g.user.id}")


@app.route("/users/add_like/<int:message_id>", methods=["POST"])
def messages_update_likes(message_id):
    """ Add like to message/user as long as it isn't the logged in users message"""
    user = User.query.get(g.user.id)

    message = Message.query.get(message_id)
    print(user.likes)
    current_like = Likes(user_id=user.id, message_id=message.id)
    print(current_like.message_id)
    # setup a likes array for all likes for current user
    all_likes = []
    # check if current user is trying to like their own message/warble
    if message.user_id != g.user.id:
        # for loop to get all message ID's into an array
        for warble in user.likes:
            all_likes.append(warble.id)
            # print(all_likes)
        # Check if current attempted like has already been liked by the logged in user, or add the like to the message
        if current_like.message_id in all_likes:
            curr_like = Likes.query.filter_by(
                user_id=user.id, message_id=message.id
            ).first()
            db.session.delete(curr_like)
            db.session.commit()
        else:
            db.session.add(current_like)
            db.session.commit()
    return redirect("/")


##############################################################################
# Homepage and error pages


@app.route("/")
def homepage():
    """Show homepage:

    - anon users: no messages
    - logged in: 100 most recent messages of followed_users
    """

    if g.user:

        # query for all like objects available
        all_likes = Likes.query.filter_by(user_id=g.user.id).all()
        likes = []
        # for each like object, we pull out the message id and append it to the likes array
        for like in all_likes:
            likes.append(like.message_id)

        all_following_objects = g.user.following
        following = []
        for user_object in all_following_objects:
            following.append(user_object.id)

        following.append(g.user.id)
        messages = (
            Message.query.order_by(Message.timestamp.desc())
            .filter(Message.user_id.in_(following))
            .limit(100)
            .all()
        )
        return render_template(
            "home.html", messages=messages, following=following, likes=likes
        )

    else:
        return render_template("home-anon.html")


##############################################################################
# Turn off all caching in Flask
#   (useful for dev; in production, this kind of stuff is typically
#   handled elsewhere)
#
# https://stackoverflow.com/questions/34066804/disabling-caching-in-flask


@app.after_request
def add_header(req):
    """Add non-caching headers on every request."""

    req.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    req.headers["Pragma"] = "no-cache"
    req.headers["Expires"] = "0"
    req.headers["Cache-Control"] = "public, max-age=0"
    return req
