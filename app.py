from flask import Flask, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import os

TURKEY_TZ = ZoneInfo("Europe/Istanbul")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "meetchat-dev-only-change-via-env",
)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///meetchat.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

COVER_IMAGES = [
    "img/cover-coffee.jpg",
    "img/cover-walk.jpg",
    "img/cover-games.jpg",
    "img/cover-concert.jpg",
]


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    date = db.Column(db.String(20), nullable=False)
    time = db.Column(db.String(10), nullable=False)
    location = db.Column(db.String(200), nullable=False)
    visibility = db.Column(
        db.String(20),
        nullable=False,
        default="public",
        server_default="public",
    )
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User", backref="activities")

    __table_args__ = (
        db.CheckConstraint(
            "visibility IN ('public', 'friends')",
            name="ck_activity_visibility",
        ),
    )


VALID_ACTIVITY_VISIBILITIES = ("public", "friends")
VISIBILITY_LABELS = {
    "public": "Herkese açık",
    "friends": "Sadece arkadaşlar",
}


class ActivityParticipant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="activities_joined")
    activity = db.relationship("Activity", backref="participants")

    __table_args__ = (
        db.UniqueConstraint("user_id", "activity_id", name="uq_user_activity"),
        db.CheckConstraint(
            "status IN ('joined', 'maybe')",
            name="ck_participant_status",
        ),
    )


VALID_PARTICIPANT_STATUSES = ("joined", "maybe")
VALID_HOME_FILTERS = ("all", "mine", "joined")
VALID_FRIENDSHIP_STATUSES = ("pending", "accepted", "rejected")


def parse_home_filter(raw):
    value = (raw or "all").strip()
    return value if value in VALID_HOME_FILTERS else "all"


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id], backref="sent_friendships")
    receiver = db.relationship(
        "User", foreign_keys=[receiver_id], backref="received_friendships"
    )

    __table_args__ = (
        db.UniqueConstraint("sender_id", "receiver_id", name="uq_friendship_pair"),
        db.CheckConstraint("sender_id != receiver_id", name="ck_no_self_friend"),
        db.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_friendship_status",
        ),
    )


COMMENT_MAX_LENGTH = 500


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=False)
    body = db.Column(db.String(COMMENT_MAX_LENGTH), nullable=False)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    user = db.relationship("User", backref="comments")
    activity = db.relationship("Activity", backref="comments")


with app.app_context():
    db.create_all()


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if user is None:
        session.clear()
    return user


def get_friendship(user_a_id, user_b_id):
    return Friendship.query.filter(
        db.or_(
            db.and_(
                Friendship.sender_id == user_a_id,
                Friendship.receiver_id == user_b_id,
            ),
            db.and_(
                Friendship.sender_id == user_b_id,
                Friendship.receiver_id == user_a_id,
            ),
        )
    ).first()


def friendship_ui_state(current_user_id, other_user_id, friendship):
    if friendship is None or friendship.status == "rejected":
        return "add"
    if friendship.status == "accepted":
        return "friends"
    if friendship.status == "pending":
        if friendship.sender_id == current_user_id:
            return "sent"
        if friendship.receiver_id == current_user_id:
            return "incoming"
    return "add"


def get_accepted_friend_ids(user_id):
    friendships = Friendship.query.filter(
        Friendship.status == "accepted",
        db.or_(
            Friendship.sender_id == user_id,
            Friendship.receiver_id == user_id,
        ),
    ).all()
    friend_ids = set()
    for friendship in friendships:
        if friendship.sender_id == user_id:
            friend_ids.add(friendship.receiver_id)
        else:
            friend_ids.add(friendship.sender_id)
    return friend_ids


def are_friends(user_a_id, user_b_id):
    friendship = get_friendship(user_a_id, user_b_id)
    return friendship is not None and friendship.status == "accepted"


def can_view_activity(user, activity, friend_ids=None):
    if activity.visibility == "public":
        return True
    if activity.creator_id == user.id:
        return True
    if activity.visibility == "friends":
        if friend_ids is not None:
            return activity.creator_id in friend_ids
        return are_friends(user.id, activity.creator_id)
    return False


def get_viewable_activity(activity_id, user, friend_ids=None):
    activity = db.session.get(Activity, activity_id)
    if activity is None:
        return None
    if not can_view_activity(user, activity, friend_ids=friend_ids):
        return None
    return activity


def is_activity_owner(user, activity):
    return activity.creator_id == user.id


def get_editable_activity(activity_id, user):
    activity = db.session.get(Activity, activity_id)
    if activity is None or not is_activity_owner(user, activity):
        return None
    return activity


def parse_activity_form():
    return {
        "title": request.form.get("title", "").strip(),
        "description": request.form.get("description", "").strip(),
        "date": request.form.get("date", "").strip(),
        "time": request.form.get("time", "").strip(),
        "location": request.form.get("location", "").strip(),
        "visibility": request.form.get("visibility", "public").strip() or "public",
    }


def get_now_turkey():
    return datetime.now(TURKEY_TZ).replace(second=0, microsecond=0)


def parse_activity_datetime_local(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=TURKEY_TZ)


def is_activity_datetime_in_past(date_str, time_str):
    return parse_activity_datetime_local(date_str, time_str) < get_now_turkey()


def validate_activity_form(form_data, original_date=None, original_time=None):
    if (
        not form_data["title"]
        or not form_data["description"]
        or not form_data["date"]
        or not form_data["time"]
    ):
        return "Lütfen tüm zorunlu alanları doldurun."
    try:
        datetime.strptime(form_data["date"], "%Y-%m-%d")
    except ValueError:
        return "Geçerli bir tarih girin."
    try:
        datetime.strptime(form_data["time"], "%H:%M")
    except ValueError:
        return "Saati 14:30 formatında girin."
    if form_data["visibility"] not in VALID_ACTIVITY_VISIBILITIES:
        return "Lütfen geçerli bir görünürlük seçin."
    datetime_unchanged = (
        original_date is not None
        and original_time is not None
        and form_data["date"] == original_date
        and form_data["time"] == original_time
    )
    if not datetime_unchanged and is_activity_datetime_in_past(
        form_data["date"], form_data["time"]
    ):
        return "Etkinlik tarihi ve saati geçmiş olamaz."
    return None


def format_activity_datetime(date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        months = [
            "", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
            "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
        ]
        days = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        return f"{days[dt.weekday()]}, {dt.day} {months[dt.month]} {dt.strftime('%H:%M')}"
    except ValueError:
        return f"{date_str} {time_str}"


def format_comment_datetime(dt):
    if dt is None:
        return ""
    # SQLite naive datetime olarak saklar; bu değerler UTC kabul edilir.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(TURKEY_TZ)
    months = [
        "", "Oca", "Şub", "Mar", "Nis", "May", "Haz",
        "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
    ]
    return (
        f"{local_dt.day} {months[local_dt.month]} {local_dt.year}, "
        f"{local_dt.strftime('%H:%M')}"
    )


def render_activity_detail(activity, current_user=None, error=None, form_body=""):
    joined_count = sum(1 for p in activity.participants if p.status == "joined")
    maybe_count = sum(1 for p in activity.participants if p.status == "maybe")
    comments = (
        Comment.query.filter_by(activity_id=activity.id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    comment_items = [
        {
            "author_name": comment.user.full_name,
            "body": comment.body,
            "created_at": format_comment_datetime(comment.created_at),
        }
        for comment in comments
    ]
    is_owner = (
        current_user is not None and is_activity_owner(current_user, activity)
    )

    return render_template(
        "activity_detail.html",
        activity=activity,
        comments=comment_items,
        cover_image=COVER_IMAGES[activity.id % len(COVER_IMAGES)],
        datetime=format_activity_datetime(activity.date, activity.time),
        visibility_label=VISIBILITY_LABELS.get(activity.visibility, "Herkese açık"),
        joined_count=joined_count,
        maybe_count=maybe_count,
        is_owner=is_owner,
        error=error,
        form_body=form_body,
        comment_max_length=COMMENT_MAX_LENGTH,
    )


@app.route("/")
def home():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friend_ids = get_accepted_friend_ids(current_user.id)
    search_q = request.args.get("q", "").strip()
    activity_filter = parse_home_filter(request.args.get("filter"))

    query = Activity.query
    if activity_filter == "mine":
        query = query.filter(Activity.creator_id == current_user.id)
    elif activity_filter == "joined":
        query = query.join(ActivityParticipant).filter(
            ActivityParticipant.user_id == current_user.id,
            ActivityParticipant.status == "joined",
        )

    if search_q:
        query = query.filter(Activity.title.ilike(f"%{search_q}%"))

    activities_db = query.order_by(Activity.date.asc(), Activity.time.asc()).all()
    activities = []
    for activity in activities_db:
        if not can_view_activity(current_user, activity, friend_ids=friend_ids):
            continue
        joined_count = sum(1 for p in activity.participants if p.status == "joined")
        maybe_count = sum(1 for p in activity.participants if p.status == "maybe")
        user_participation = next(
            (p for p in activity.participants if p.user_id == current_user.id),
            None,
        )
        activities.append(
            {
                "id": activity.id,
                "creator_name": activity.creator.full_name,
                "creator_avatar": "img/avatar-user.jpg",
                "title": activity.title,
                "description": activity.description,
                "datetime": format_activity_datetime(activity.date, activity.time),
                "location": activity.location,
                "cover_image": COVER_IMAGES[activity.id % len(COVER_IMAGES)],
                "joined_count": joined_count,
                "maybe_count": maybe_count,
                "user_status": user_participation.status if user_participation else None,
                "comment_count": len(activity.comments),
                "visibility": activity.visibility,
                "visibility_label": VISIBILITY_LABELS.get(
                    activity.visibility, "Herkese açık"
                ),
            }
        )

    first_name = current_user.full_name.split()[0]
    user = {
        "name": first_name,
        "avatar": "img/avatar-user.jpg",
    }

    has_active_search = bool(search_q) or activity_filter != "all"

    return render_template(
        "index.html",
        activities=activities,
        user=user,
        q=search_q,
        activity_filter=activity_filter,
        has_active_search=has_active_search,
    )


@app.route("/create-activity", methods=["GET", "POST"])
def create_activity():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    if request.method == "GET":
        min_date = datetime.now(TURKEY_TZ).strftime("%Y-%m-%d")
        return render_template("create_activity.html", min_date=min_date)

    form_data = parse_activity_form()
    min_date = datetime.now(TURKEY_TZ).strftime("%Y-%m-%d")

    print("FORM DATA:", request.form)
    print("title:", repr(form_data["title"]))
    print("description:", repr(form_data["description"]))
    print("date:", repr(form_data["date"]))
    print("time:", repr(form_data["time"]))
    print("location:", repr(form_data["location"]))
    print("visibility:", repr(form_data["visibility"]))

    error = validate_activity_form(form_data)
    if error:
        return render_template(
            "create_activity.html",
            error=error,
            form_data=form_data,
            min_date=min_date,
        )

    activity = Activity(
        title=form_data["title"],
        description=form_data["description"],
        date=form_data["date"],
        time=form_data["time"],
        location=form_data["location"],
        visibility=form_data["visibility"],
        creator_id=current_user.id,
    )
    db.session.add(activity)
    db.session.commit()

    return redirect(url_for("home"))


@app.route("/activity/<int:activity_id>/respond", methods=["POST"])
def respond_activity(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    status = request.form.get("status", "").strip()
    if status not in VALID_PARTICIPANT_STATUSES:
        return redirect(url_for("home"))

    activity = db.session.get(Activity, activity_id)
    if activity is None:
        return redirect(url_for("home"))

    if not can_view_activity(current_user, activity):
        return redirect(url_for("home"))

    participation = ActivityParticipant.query.filter_by(
        user_id=current_user.id,
        activity_id=activity_id,
    ).first()

    if participation is None:
        db.session.add(
            ActivityParticipant(
                user_id=current_user.id,
                activity_id=activity_id,
                status=status,
            )
        )
    elif participation.status == status:
        db.session.delete(participation)
    else:
        participation.status = status

    db.session.commit()
    return redirect(url_for("home"))


@app.route("/activity/<int:activity_id>")
def activity_detail(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friend_ids = get_accepted_friend_ids(current_user.id)
    activity = get_viewable_activity(activity_id, current_user, friend_ids=friend_ids)
    if activity is None:
        return redirect(url_for("home"))

    return render_activity_detail(activity, current_user=current_user)


@app.route("/activity/<int:activity_id>/edit", methods=["GET", "POST"])
def edit_activity(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    activity = get_editable_activity(activity_id, current_user)
    if activity is None:
        return redirect(url_for("home"))

    if request.method == "GET":
        form_data = {
            "title": activity.title,
            "description": activity.description,
            "date": activity.date,
            "time": activity.time,
            "location": activity.location,
            "visibility": activity.visibility,
        }
        return render_template(
            "edit_activity.html",
            activity=activity,
            form_data=form_data,
        )

    form_data = parse_activity_form()
    error = validate_activity_form(
        form_data,
        original_date=activity.date,
        original_time=activity.time,
    )
    if error:
        return render_template(
            "edit_activity.html",
            activity=activity,
            form_data=form_data,
            error=error,
        )

    activity.title = form_data["title"]
    activity.description = form_data["description"]
    activity.date = form_data["date"]
    activity.time = form_data["time"]
    activity.location = form_data["location"]
    activity.visibility = form_data["visibility"]
    db.session.commit()

    return redirect(url_for("activity_detail", activity_id=activity_id))


@app.route("/activity/<int:activity_id>/delete", methods=["POST"])
def delete_activity(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    activity = get_editable_activity(activity_id, current_user)
    if activity is None:
        return redirect(url_for("home"))

    try:
        Comment.query.filter_by(activity_id=activity.id).delete()
        ActivityParticipant.query.filter_by(activity_id=activity.id).delete()
        db.session.delete(activity)
        db.session.commit()
    except Exception:
        app.logger.exception(
            "Etkinlik silinirken hata oluştu (activity_id=%s, user_id=%s).",
            activity_id,
            current_user.id,
        )
        db.session.rollback()
        return redirect(url_for("home"))

    return redirect(url_for("home"))


@app.route("/activity/<int:activity_id>/comments", methods=["POST"])
def add_comment(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friend_ids = get_accepted_friend_ids(current_user.id)
    activity = get_viewable_activity(activity_id, current_user, friend_ids=friend_ids)
    if activity is None:
        return redirect(url_for("home"))

    body = request.form.get("body", "").strip()

    if not body:
        return render_activity_detail(
            activity,
            current_user=current_user,
            error="Lütfen bir yorum yazın.",
            form_body="",
        )

    if len(body) > COMMENT_MAX_LENGTH:
        return render_activity_detail(
            activity,
            current_user=current_user,
            error=f"Yorum en fazla {COMMENT_MAX_LENGTH} karakter olabilir.",
            form_body=body[:COMMENT_MAX_LENGTH],
        )

    db.session.add(
        Comment(
            user_id=current_user.id,
            activity_id=activity_id,
            body=body,
        )
    )
    db.session.commit()
    return redirect(url_for("activity_detail", activity_id=activity_id))

@app.route("/discover")
def discover():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    search_q = request.args.get("q", "").strip()
    query = Activity.query.filter(Activity.visibility == "public")

    if search_q:
        query = query.filter(Activity.title.ilike(f"%{search_q}%"))

    activities_db = query.order_by(Activity.date.asc(), Activity.time.asc()).all()
    activities = []
    for activity in activities_db:
        joined_count = sum(1 for p in activity.participants if p.status == "joined")
        maybe_count = sum(1 for p in activity.participants if p.status == "maybe")
        user_participation = next(
            (p for p in activity.participants if p.user_id == current_user.id),
            None,
        )
        activities.append(
            {
                "id": activity.id,
                "creator_name": activity.creator.full_name,
                "creator_avatar": "img/avatar-user.jpg",
                "title": activity.title,
                "description": activity.description,
                "datetime": format_activity_datetime(activity.date, activity.time),
                "location": activity.location,
                "cover_image": COVER_IMAGES[activity.id % len(COVER_IMAGES)],
                "joined_count": joined_count,
                "maybe_count": maybe_count,
                "user_status": user_participation.status if user_participation else None,
                "comment_count": len(activity.comments),
                "visibility": activity.visibility,
                "visibility_label": VISIBILITY_LABELS.get(
                    activity.visibility, "Herkese açık"
                ),
            }
        )

    return render_template(
        "discover.html",
        activities=activities,
        q=search_q,
    )

    
@app.route("/friends")
def friends():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    me = current_user.id

    incoming = (
        Friendship.query.filter_by(receiver_id=me, status="pending")
        .order_by(Friendship.created_at.desc())
        .all()
    )
    incoming_requests = [
        {
            "friendship_id": f.id,
            "user": f.sender,
        }
        for f in incoming
    ]

    accepted = Friendship.query.filter(
        Friendship.status == "accepted",
        db.or_(Friendship.sender_id == me, Friendship.receiver_id == me),
    ).order_by(Friendship.updated_at.desc()).all()

    friend_list = []
    for f in accepted:
        other = f.receiver if f.sender_id == me else f.sender
        friend_list.append(
            {
                "friendship_id": f.id,
                "user": other,
            }
        )

    other_users = User.query.filter(User.id != me).order_by(User.full_name).all()
    users = []
    for other in other_users:
        friendship = get_friendship(me, other.id)
        users.append(
            {
                "user": other,
                "friendship_id": friendship.id if friendship else None,
                "state": friendship_ui_state(me, other.id, friendship),
            }
        )

    return render_template(
        "friends.html",
        user={"name": current_user.full_name.split()[0]},
        incoming_requests=incoming_requests,
        friends=friend_list,
        users=users,
    )


@app.route("/friends/request/<int:user_id>", methods=["POST"])
def friends_request(user_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    if user_id == current_user.id:
        return redirect(url_for("friends"))

    other = db.session.get(User, user_id)
    if other is None:
        return redirect(url_for("friends"))

    friendship = get_friendship(current_user.id, user_id)
    if friendship is None:
        db.session.add(
            Friendship(
                sender_id=current_user.id,
                receiver_id=user_id,
                status="pending",
            )
        )
    elif friendship.status == "rejected":
        friendship.sender_id = current_user.id
        friendship.receiver_id = user_id
        friendship.status = "pending"
        friendship.updated_at = datetime.utcnow()
    # pending or accepted -> no-op

    db.session.commit()
    return redirect(url_for("friends"))


@app.route("/friends/accept/<int:friendship_id>", methods=["POST"])
def friends_accept(friendship_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friendship = db.session.get(Friendship, friendship_id)
    if (
        friendship is None
        or friendship.status != "pending"
        or friendship.receiver_id != current_user.id
    ):
        return redirect(url_for("friends"))

    friendship.status = "accepted"
    friendship.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("friends"))


@app.route("/friends/reject/<int:friendship_id>", methods=["POST"])
def friends_reject(friendship_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friendship = db.session.get(Friendship, friendship_id)
    if (
        friendship is None
        or friendship.status != "pending"
        or friendship.receiver_id != current_user.id
    ):
        return redirect(url_for("friends"))

    friendship.status = "rejected"
    friendship.updated_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("friends"))


@app.route("/friends/remove/<int:friendship_id>", methods=["POST"])
def friends_remove(friendship_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friendship = db.session.get(Friendship, friendship_id)
    if (
        friendship is None
        or friendship.status != "accepted"
        or current_user.id not in (friendship.sender_id, friendship.receiver_id)
    ):
        return redirect(url_for("friends"))

    db.session.delete(friendship)
    db.session.commit()
    return redirect(url_for("friends"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    form_data = {"email": email}

    user = User.query.filter_by(email=email).first()
    if user is None or not check_password_hash(user.password_hash, password):
        return render_template(
            "login.html",
            error="E-posta veya şifre hatalı.",
            form_data=form_data,
        )

    session.clear()
    session["user_id"] = user.id
    session["user_name"] = user.full_name

    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    full_name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")

    form_data = {"name": full_name, "email": email}

    if not full_name or not email or not password or not password_confirm:
        return render_template(
            "register.html",
            error="Lütfen tüm alanları doldurun.",
            form_data=form_data,
        )

    if password != password_confirm:
        return render_template(
            "register.html",
            error="Şifreler uyuşmuyor.",
            form_data=form_data,
        )

    if len(password) < 8:
        return render_template(
            "register.html",
            error="Şifreniz en az 8 karakter olmalıdır.",
            form_data=form_data,
        )

    if User.query.filter_by(email=email).first():
        return render_template(
            "register.html",
            error="Bu e-posta zaten kayıtlı.",
            form_data=form_data,
        )

    user = User(
        full_name=full_name,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
