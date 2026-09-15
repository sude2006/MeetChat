from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import math
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
    category = db.Column(db.String(20), nullable=True)
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
ACTIVITY_CATEGORY_LABELS = {
    "kahve": "Kahve",
    "yeme": "Yeme & İçme",
    "spor": "Spor",
    "sanat": "Sanat",
    "kitap": "Kitap",
    "doga": "Doğa",
    "gezi": "Gezi",
    "hobi": "Hobi",
    "diger": "Diğer",
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
VALID_TIME_FILTERS = ("all", "today", "tomorrow", "week")
VALID_DISCOVER_TIME_FILTERS = ("all", "today", "tomorrow", "week", "month")
DISCOVER_TIME_FILTER_LABELS = {
    "all": "Tümü",
    "today": "Bugün",
    "tomorrow": "Yarın",
    "week": "Bu Hafta",
    "month": "Bu Ay",
}
UPCOMING_LIST_TIME_FILTERS = ("all", "today", "tomorrow", "week")
UPCOMING_LIST_TIME_FILTER_LABELS = {
    "all": "Tümü",
    "today": "Bugün",
    "tomorrow": "Yarın",
    "week": "Bu Hafta",
}
UPCOMING_LIST_WINDOW_DAYS = 7
VALID_CATEGORY_FILTERS = tuple(ACTIVITY_CATEGORY_LABELS.keys())
TURKEY_CITIES = (
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara",
    "Antalya", "Ardahan", "Artvin", "Aydın", "Balıkesir", "Bartın", "Batman",
    "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur", "Bursa",
    "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne",
    "Elazığ", "Erzincan", "Erzurum", "Eskişehir", "Gaziantep", "Giresun",
    "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul", "İzmir",
    "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri",
    "Kırıkkale", "Kırklareli", "Kırşehir", "Kilis", "Kocaeli", "Konya", "Kütahya",
    "Malatya", "Manisa", "Mardin", "Mersin", "Muğla", "Muş", "Nevşehir", "Niğde",
    "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun", "Siirt", "Sinop", "Sivas",
    "Şanlıurfa", "Şırnak", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak",
    "Van", "Yalova", "Yozgat", "Zonguldak",
)
DEFAULT_DISCOVER_CITY = "İstanbul"
VALID_FRIENDSHIP_STATUSES = ("pending", "accepted", "rejected")


def parse_home_filter(raw):
    value = (raw or "all").strip()
    return value if value in VALID_HOME_FILTERS else "all"


def parse_time_filter(raw):
    value = (raw or "all").strip()
    return value if value in VALID_TIME_FILTERS else "all"


def parse_category_filter(raw):
    value = (raw or "").strip()
    return value if value in VALID_CATEGORY_FILTERS else ""


def activity_matches_time_filter(activity, time_filter):
    if time_filter == "all":
        return True
    try:
        activity_date = datetime.strptime(activity.date, "%Y-%m-%d").date()
    except ValueError:
        return False

    today = datetime.now(TURKEY_TZ).date()
    if time_filter == "today":
        return activity_date == today
    if time_filter == "tomorrow":
        return activity_date == today + timedelta(days=1)
    if time_filter == "week":
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start <= activity_date <= week_end
    if time_filter == "month":
        month_start = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        month_end = next_month - timedelta(days=1)
        return month_start <= activity_date <= month_end
    return True


def parse_upcoming_list_time_filter(raw):
    value = (raw or "all").strip()
    if value == "month":
        return "all"
    return value if value in UPCOMING_LIST_TIME_FILTERS else "all"


def is_activity_in_upcoming_list_window(activity, window_days=UPCOMING_LIST_WINDOW_DAYS):
    try:
        activity_date = datetime.strptime(activity.date, "%Y-%m-%d").date()
    except ValueError:
        return False

    today = datetime.now(TURKEY_TZ).date()
    window_end = today + timedelta(days=window_days - 1)
    return today <= activity_date <= window_end


def activity_matches_upcoming_list_time_filter(activity, time_filter):
    if not is_activity_in_upcoming_list_window(activity):
        return False
    if time_filter in ("all", "week"):
        return True

    try:
        activity_date = datetime.strptime(activity.date, "%Y-%m-%d").date()
    except ValueError:
        return False

    today = datetime.now(TURKEY_TZ).date()
    if time_filter == "today":
        return activity_date == today
    if time_filter == "tomorrow":
        return activity_date == today + timedelta(days=1)
    return True


def parse_discover_time_filter(raw):
    value = (raw or "all").strip()
    return value if value in VALID_DISCOVER_TIME_FILTERS else "all"


def parse_discover_city_filter(raw):
    value = (raw or "").strip()
    if not value:
        return ""
    for city in TURKEY_CITIES:
        if city.casefold() == value.casefold():
            return city
    return ""


ALLOWED_DETAIL_FROM = {
    "home",
    "discover",
    "discover_upcoming",
    "discover_recent",
    "discover_people",
    "profile",
    "notifications",
    "user_profile",
}
ALLOWED_RESPOND_ORIGINS = {"detail", "home", "discover"}


def parse_user_profile_id(raw):
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        return None
    if user_id < 1:
        return None
    return user_id


def parse_detail_context(from_raw, q_raw="", filter_raw="all"):
    from_page = from_raw if from_raw in ALLOWED_DETAIL_FROM else "home"
    q = (q_raw or "").strip()
    activity_filter = parse_home_filter(filter_raw)
    return from_page, q, activity_filter


def build_discover_upcoming_url(
    q="",
    time_filter="all",
    category_filter="",
    city_filter="",
):
    kwargs = {}
    if q:
        kwargs["q"] = q
    if time_filter != "all":
        kwargs["time"] = time_filter
    if category_filter:
        kwargs["category"] = category_filter
    if city_filter:
        kwargs["city"] = city_filter
    return url_for("discover_upcoming", **kwargs)


def build_discover_recent_url(
    q="",
    category_filter="",
    city_filter="",
):
    kwargs = {}
    if q:
        kwargs["q"] = q
    if category_filter:
        kwargs["category"] = category_filter
    if city_filter:
        kwargs["city"] = city_filter
    return url_for("discover_recent", **kwargs)


def build_discover_people_url(q=""):
    kwargs = {}
    if q:
        kwargs["q"] = q
    return url_for("discover_people", **kwargs)


def build_list_back_url(
    from_page,
    q="",
    activity_filter="all",
    user_id=None,
    detail_time="all",
    detail_category="",
    detail_city="",
):
    if from_page == "discover":
        return url_for("discover", q=q) if q else url_for("discover")
    if from_page == "discover_upcoming":
        return build_discover_upcoming_url(
            q, detail_time, detail_category, detail_city
        )
    if from_page == "discover_recent":
        return build_discover_recent_url(
            q, detail_category, detail_city
        )
    if from_page == "discover_people":
        return build_discover_people_url(q)
    if from_page == "home":
        kwargs = {}
        if q:
            kwargs["q"] = q
        if activity_filter != "all":
            kwargs["filter"] = activity_filter
        return url_for("home", **kwargs)
    if from_page == "profile":
        return url_for("profile")
    if from_page == "notifications":
        return url_for("notifications")
    if from_page == "user_profile":
        profile_user_id = parse_user_profile_id(user_id)
        if profile_user_id is None:
            return url_for("home")
        return url_for("user_profile", user_id=profile_user_id)
    return url_for("home")


def build_detail_url(
    activity_id,
    from_page,
    q="",
    activity_filter="all",
    user_id=None,
    time_filter="all",
    category_filter="",
    city_filter="",
):
    kwargs = {"activity_id": activity_id, "source": from_page}
    if from_page == "discover":
        kwargs["q"] = q
    elif from_page in ("discover_upcoming", "discover_recent"):
        if q:
            kwargs["q"] = q
        if time_filter != "all":
            kwargs["time"] = time_filter
        if category_filter:
            kwargs["category"] = category_filter
        if city_filter:
            kwargs["city"] = city_filter
    elif from_page == "home":
        kwargs["q"] = q
        kwargs["filter"] = activity_filter
    elif from_page == "user_profile":
        profile_user_id = parse_user_profile_id(user_id)
        if profile_user_id is not None:
            kwargs["user_id"] = profile_user_id
    return url_for("activity_detail", **kwargs)


def build_user_profile_url(
    profile_user_id,
    from_activity_id=None,
    from_page="home",
    q="",
    activity_filter="all",
    detail_user_id=None,
):
    kwargs = {"user_id": profile_user_id}
    activity_id = parse_user_profile_id(from_activity_id)
    if activity_id is None:
        return url_for("user_profile", **kwargs)

    from_page, q, activity_filter = parse_detail_context(from_page, q, activity_filter)
    kwargs["from_activity"] = activity_id
    kwargs["source"] = from_page
    if from_page in ("home", "discover") and q:
        kwargs["q"] = q
    if from_page == "home" and activity_filter != "all":
        kwargs["filter"] = activity_filter
    if from_page == "user_profile":
        nested_id = parse_user_profile_id(detail_user_id)
        if nested_id is not None:
            kwargs["detail_user_id"] = nested_id
    return url_for("user_profile", **kwargs)


def user_profile_url_from_values(profile_user_id, values):
    return build_user_profile_url(
        profile_user_id,
        from_activity_id=values.get("from_activity"),
        from_page=values.get("source", ""),
        q=values.get("q", ""),
        activity_filter=values.get("filter", "all"),
        detail_user_id=values.get("detail_user_id"),
    )


def redirect_after_respond(
    activity_id, origin, from_page="home", q="", activity_filter="all", user_id=None
):
    from_page, q, activity_filter = parse_detail_context(from_page, q, activity_filter)

    if origin not in ALLOWED_RESPOND_ORIGINS:
        return redirect(url_for("home"))

    if origin == "detail":
        return redirect(
            build_detail_url(
                activity_id, from_page, q, activity_filter, user_id=user_id
            )
        )
    if origin == "discover":
        return redirect(url_for("discover", q=q) if q else url_for("discover"))
    if origin == "home":
        kwargs = {}
        if q:
            kwargs["q"] = q
        if activity_filter != "all":
            kwargs["filter"] = activity_filter
        return redirect(url_for("home", **kwargs))
    return redirect(url_for("home"))


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


VALID_NOTIFICATION_TYPES = (
    "friend_request",
    "friend_accept",
    "activity_join",
    "activity_comment",
    "activity_time_change",
)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, index=True
    )
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=True)
    friendship_id = db.Column(
        db.Integer, db.ForeignKey("friendship.id"), nullable=True
    )
    comment_id = db.Column(db.Integer, db.ForeignKey("comment.id"), nullable=True)
    type = db.Column(db.String(40), nullable=False)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    is_dismissed = db.Column(db.Boolean, nullable=False, default=False)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    old_time = db.Column(db.String(10), nullable=True)
    new_time = db.Column(db.String(10), nullable=True)
    old_date = db.Column(db.String(20), nullable=True)
    new_date = db.Column(db.String(20), nullable=True)
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    recipient = db.relationship(
        "User", foreign_keys=[recipient_id], backref="notifications_received"
    )
    actor = db.relationship(
        "User", foreign_keys=[actor_id], backref="notifications_acted"
    )
    activity = db.relationship("Activity", backref="notifications")
    friendship = db.relationship("Friendship", backref="notifications")
    comment = db.relationship("Comment", backref="notifications")

    __table_args__ = (
        db.CheckConstraint(
            "type IN ("
            "'friend_request', 'friend_accept', 'activity_join', "
            "'activity_comment', 'activity_time_change'"
            ")",
            name="ck_notification_type",
        ),
        db.Index("ix_notification_recipient_created", "recipient_id", "created_at"),
        db.Index(
            "ix_notification_recipient_unread",
            "recipient_id",
            "is_dismissed",
            "is_read",
        ),
    )


def _ensure_friend_accept_notification_type():
    if db.engine.dialect.name != "sqlite":
        return
    with db.engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        create_sql = conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='notification'"
            )
        ).scalar()
        if not create_sql or "friend_accept" in create_sql:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            return

        new_sql = create_sql.replace(
            "'activity_time_change'",
            "'activity_time_change', 'friend_accept'",
            1,
        )
        if 'CREATE TABLE "notification"' in new_sql:
            new_sql = new_sql.replace(
                'CREATE TABLE "notification"',
                'CREATE TABLE "notification__new"',
                1,
            )
        else:
            new_sql = new_sql.replace(
                "CREATE TABLE notification",
                "CREATE TABLE notification__new",
                1,
            )
        if "notification__new" not in new_sql:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            return
        conn.execute(text(new_sql))
        conn.execute(
            text("INSERT INTO notification__new SELECT * FROM notification")
        )
        conn.execute(text("DROP TABLE notification"))
        conn.execute(
            text("ALTER TABLE notification__new RENAME TO notification")
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_notification_recipient_created "
                "ON notification (recipient_id, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_notification_recipient_unread "
                "ON notification (recipient_id, is_dismissed, is_read)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_notification_recipient_id "
                "ON notification (recipient_id)"
            )
        )
        conn.execute(text("PRAGMA foreign_keys=ON"))


with app.app_context():
    db.create_all()
    _ensure_friend_accept_notification_type()


NOTIFICATION_FIELD_UNSET = object()


def _utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_field(value):
    return None if value is NOTIFICATION_FIELD_UNSET else value


def _is_missing_notification_field(value):
    return value is NOTIFICATION_FIELD_UNSET or value is None


def create_or_update_notification(
    *,
    recipient_id,
    type,
    actor_id=NOTIFICATION_FIELD_UNSET,
    activity_id=NOTIFICATION_FIELD_UNSET,
    friendship_id=NOTIFICATION_FIELD_UNSET,
    comment_id=NOTIFICATION_FIELD_UNSET,
    old_time=NOTIFICATION_FIELD_UNSET,
    new_time=NOTIFICATION_FIELD_UNSET,
    old_date=NOTIFICATION_FIELD_UNSET,
    new_date=NOTIFICATION_FIELD_UNSET,
):
    if type not in VALID_NOTIFICATION_TYPES:
        return None
    if not recipient_id:
        return None
    if (
        actor_id is not NOTIFICATION_FIELD_UNSET
        and actor_id is not None
        and recipient_id == actor_id
    ):
        return None

    if type == "friend_request":
        if _is_missing_notification_field(friendship_id) or _is_missing_notification_field(
            actor_id
        ):
            return None
        existing = Notification.query.filter_by(
            recipient_id=recipient_id,
            type=type,
            friendship_id=friendship_id,
        ).first()
    elif type == "friend_accept":
        if _is_missing_notification_field(friendship_id) or _is_missing_notification_field(
            actor_id
        ):
            return None
        existing = Notification.query.filter_by(
            recipient_id=recipient_id,
            type=type,
            friendship_id=friendship_id,
        ).first()
    elif type == "activity_join":
        if _is_missing_notification_field(activity_id) or _is_missing_notification_field(
            actor_id
        ):
            return None
        existing = Notification.query.filter_by(
            recipient_id=recipient_id,
            type=type,
            activity_id=activity_id,
            actor_id=actor_id,
        ).first()
    elif type == "activity_comment":
        if (
            _is_missing_notification_field(comment_id)
            or _is_missing_notification_field(activity_id)
            or _is_missing_notification_field(actor_id)
        ):
            return None
        existing = Notification.query.filter_by(
            recipient_id=recipient_id,
            type=type,
            comment_id=comment_id,
        ).first()
    elif type == "activity_time_change":
        if _is_missing_notification_field(activity_id) or _is_missing_notification_field(
            actor_id
        ):
            return None

        time_old_provided = old_time is not NOTIFICATION_FIELD_UNSET
        time_new_provided = new_time is not NOTIFICATION_FIELD_UNSET
        if time_old_provided != time_new_provided:
            return None

        date_old_provided = old_date is not NOTIFICATION_FIELD_UNSET
        date_new_provided = new_date is not NOTIFICATION_FIELD_UNSET
        if date_old_provided != date_new_provided:
            return None

        time_pair_complete = (
            time_old_provided
            and time_new_provided
            and old_time is not None
            and new_time is not None
        )
        date_pair_complete = (
            date_old_provided
            and date_new_provided
            and old_date is not None
            and new_date is not None
        )
        if not time_pair_complete and not date_pair_complete:
            return None

        existing = Notification.query.filter_by(
            recipient_id=recipient_id,
            type=type,
            activity_id=activity_id,
        ).first()
    else:
        return None

    field_values = {
        "actor_id": actor_id,
        "activity_id": activity_id,
        "friendship_id": friendship_id,
        "comment_id": comment_id,
        "old_time": old_time,
        "new_time": new_time,
        "old_date": old_date,
        "new_date": new_date,
    }
    now = _utc_now_naive()

    if existing is None:
        notification = Notification(
            recipient_id=recipient_id,
            type=type,
            actor_id=_resolve_field(actor_id),
            activity_id=_resolve_field(activity_id),
            friendship_id=_resolve_field(friendship_id),
            comment_id=_resolve_field(comment_id),
            old_time=_resolve_field(old_time),
            new_time=_resolve_field(new_time),
            old_date=_resolve_field(old_date),
            new_date=_resolve_field(new_date),
            is_read=False,
            is_dismissed=False,
            dismissed_at=None,
            created_at=now,
            updated_at=now,
        )
        db.session.add(notification)
        return notification

    for name, value in field_values.items():
        if value is not NOTIFICATION_FIELD_UNSET:
            setattr(existing, name, value)
    existing.is_read = False
    existing.is_dismissed = False
    existing.dismissed_at = None
    existing.created_at = now
    existing.updated_at = now
    return existing


def get_unread_notification_count(user_id):
    if not user_id:
        return 0
    return Notification.query.filter_by(
        recipient_id=user_id,
        is_read=False,
        is_dismissed=False,
    ).count()


def format_relative_time(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(TURKEY_TZ)
    now_local = datetime.now(TURKEY_TZ)
    delta_seconds = (now_local - local_dt).total_seconds()
    if delta_seconds < 60:
        return "Az önce"

    minutes = int(delta_seconds // 60)
    if minutes <= 59:
        return f"{minutes} dk önce"

    hours = int(delta_seconds // 3600)
    local_date = local_dt.date()
    today = now_local.date()
    if local_date == today and 1 <= hours <= 23:
        return f"{hours} sa önce"

    yesterday = today - timedelta(days=1)
    if local_date == yesterday:
        return "Dün"

    days = (today - local_date).days
    if 2 <= days <= 29:
        return f"{days} gün önce"

    return f"{local_dt.day} {PROFILE_MONTHS[local_dt.month]} {local_dt.year}"


def format_added_ago_label(dt):
    if dt is None:
        return "Yakın zamanda eklendi"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(TURKEY_TZ)
    now_local = datetime.now(TURKEY_TZ)
    delta_seconds = (now_local - local_dt).total_seconds()
    if delta_seconds < 60:
        return "Az önce eklendi"

    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"{minutes} dk önce eklendi"

    hours = int(delta_seconds // 3600)
    local_date = local_dt.date()
    today = now_local.date()
    if local_date == today:
        if hours < 6:
            return f"{hours} saat önce eklendi"
        return "Bugün eklendi"

    yesterday = today - timedelta(days=1)
    if local_date == yesterday:
        return "Dün eklendi"

    days = (today - local_date).days
    if days == 7:
        return "1 hafta önce eklendi"
    if 2 <= days <= 6:
        return f"{days} gün önce eklendi"
    return f"{local_dt.day} {PROFILE_MONTHS[local_dt.month]} eklendi"


def format_created_ago_label(dt):
    if dt is None:
        return "Yakın zamanda oluşturdu"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(TURKEY_TZ)
    now_local = datetime.now(TURKEY_TZ)
    delta_seconds = (now_local - local_dt).total_seconds()
    if delta_seconds < 60:
        return "Az önce oluşturdu"

    minutes = int(delta_seconds // 60)
    if minutes < 60:
        return f"{minutes} dk önce oluşturdu"

    hours = int(delta_seconds // 3600)
    local_date = local_dt.date()
    today = now_local.date()
    if local_date == today:
        if hours < 6:
            return f"{hours} saat önce oluşturdu"
        return "Bugün oluşturdu"

    yesterday = today - timedelta(days=1)
    if local_date == yesterday:
        return "Dün oluşturdu"

    days = (today - local_date).days
    if days == 7:
        return "1 hafta önce oluşturdu"
    if 2 <= days <= 13:
        return f"{days} gün önce oluşturdu"
    if 14 <= days <= 20:
        return "2 hafta önce oluşturdu"
    return f"{local_dt.day} {PROFILE_MONTHS[local_dt.month]} oluşturdu"


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if user is None:
        session.clear()
    return user


@app.context_processor
def inject_unread_notification_count():
    user = get_current_user()
    if user is None:
        return {"unread_notification_count": 0}
    return {
        "unread_notification_count": get_unread_notification_count(user.id)
    }


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
        "category": request.form.get("category", "").strip(),
        "visibility": request.form.get("visibility", "public").strip() or "public",
    }


def get_now_turkey():
    return datetime.now(TURKEY_TZ).replace(second=0, microsecond=0)


def parse_activity_datetime_local(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=TURKEY_TZ)


def is_activity_datetime_in_past(date_str, time_str):
    return parse_activity_datetime_local(date_str, time_str) <= get_now_turkey()


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
    if form_data["category"] not in ACTIVITY_CATEGORY_LABELS:
        return "Lütfen geçerli bir kategori seçin."
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


def format_activity_datetime_compact(date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return f"{dt.day} {PROFILE_MONTHS[dt.month]} · {dt.strftime('%H:%M')}"
    except ValueError:
        return f"{date_str} {time_str}"


WEEKDAY_NAMES = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar",
]

PROFILE_MONTHS = [
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


def format_activity_time_label(date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        activity_date = dt.date()
        today = datetime.now(TURKEY_TZ).date()
        time_part = dt.strftime("%H:%M")

        if activity_date == today:
            return f"Bugün • {time_part}", True
        if activity_date == today + timedelta(days=1):
            return f"Yarın • {time_part}", False

        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        if week_start <= activity_date <= week_end:
            return f"{WEEKDAY_NAMES[dt.weekday()]} • {time_part}", False

        return f"{dt.day} {PROFILE_MONTHS[dt.month]} • {time_part}", False
    except ValueError:
        return f"{date_str} {time_str}", False


def format_upcoming_when_parts(date_str, time_str):
    weekday_short = ("Pzt", "Sal", "Çar", "Per", "Cuma", "Cmt", "Paz")
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        activity_date = dt.date()
        today = datetime.now(TURKEY_TZ).date()
        clock_label = dt.strftime("%H:%M")
        weekday = weekday_short[dt.weekday()]
        if activity_date == today:
            return {
                "day_label": "Bugün",
                "clock_label": clock_label,
                "date_label": "",
                "is_today": True,
            }
        if activity_date == today + timedelta(days=1):
            return {
                "day_label": "Yarın",
                "clock_label": clock_label,
                "date_label": "",
                "is_today": False,
            }
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        if week_start <= activity_date <= week_end:
            return {
                "day_label": weekday,
                "clock_label": clock_label,
                "date_label": "",
                "is_today": False,
            }
        return {
            "day_label": weekday,
            "clock_label": clock_label,
            "date_label": f"{dt.day} {PROFILE_MONTHS[dt.month]}",
            "is_today": False,
        }
    except ValueError:
        return {
            "day_label": date_str,
            "clock_label": time_str,
            "date_label": "",
            "is_today": False,
        }


def format_display_name(name):
    if not name:
        return ""
    parts = []
    for part in name.strip().split():
        first = part[0]
        if first == "i":
            first = "İ"
        elif first == "ı":
            first = "I"
        else:
            first = first.upper()
        parts.append(first + part[1:] if len(part) > 1 else first)
    return " ".join(parts)


def format_short_display_name(name):
    formatted = format_display_name(name)
    parts = formatted.split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[1][0]}."


def display_first_name(name):
    formatted = format_display_name(name)
    if not formatted:
        return ""
    return formatted.split()[0]


def letter_avatar_initial(name):
    formatted = format_display_name(name)
    return formatted[0] if formatted else "?"


LETTER_AVATAR_COLORS = (
    "#E97B8F",
    "#F2A07B",
    "#E8C15C",
    "#7DBA93",
    "#6FC9B6",
    "#62C5D4",
    "#8CB6E8",
    "#A996E8",
    "#C49AD9",
    "#D98EA8",
    "#C9AE8B",
    "#7FA5C9",
)


def letter_avatar_color(name):
    key = (name or "").strip().casefold()
    if not key:
        return LETTER_AVATAR_COLORS[0]
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return LETTER_AVATAR_COLORS[sum(digest) % len(LETTER_AVATAR_COLORS)]


def build_letter_avatar(name, photo_url=None):
    display_name = format_display_name(name)
    return {
        "initial": letter_avatar_initial(name),
        "color": letter_avatar_color(name),
        "name": display_name,
        "photo_url": photo_url or "",
    }


def avatar_for_user(user, photo_url=None):
    if user is None:
        return build_letter_avatar("", photo_url=photo_url)
    return build_letter_avatar(user.full_name, photo_url=photo_url)


@app.context_processor
def inject_avatar_helpers():
    return {
        "build_letter_avatar": build_letter_avatar,
        "avatar_for_user": avatar_for_user,
    }


def build_participant_display(activity, current_user_id, friend_ids):
    joined = [p for p in activity.participants if p.status == "joined"]
    joined_count = len(joined)
    maybe_count = sum(1 for p in activity.participants if p.status == "maybe")
    friend_joined = [
        p for p in joined
        if p.user_id in friend_ids and p.user_id != current_user_id
    ]

    avatars = [avatar_for_user(p.user) for p in joined[:3]]
    lead_name = ""

    if joined_count == 0:
        summary = "Henüz kimse katılmıyor"
    elif friend_joined:
        lead_name = display_first_name(friend_joined[0].user.full_name)
        other_friends = len(friend_joined) - 1
        if other_friends > 0:
            summary = f"{lead_name} ve {other_friends} arkadaşın katılıyor"
        elif joined_count > 1:
            summary = f"{lead_name} ve {joined_count - 1} kişi katılıyor"
        else:
            summary = f"{lead_name} katılıyor"
    elif joined_count == 1:
        lead_name = display_first_name(joined[0].user.full_name)
        summary = f"{lead_name} katılıyor"
    else:
        summary = f"{joined_count} kişi katılıyor"

    return {
        "avatars": avatars,
        "summary": summary,
        "lead_name": lead_name,
        "joined_count": joined_count,
        "maybe_count": maybe_count,
    }


def format_plan_date_short(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.day} {PROFILE_MONTHS[dt.month]}"
    except ValueError:
        return date_str


def build_created_plan_view(activity, category_key=""):
    key = category_key if category_key in ACTIVITY_CATEGORY_LABELS else ""
    visibility_label = (
        "Herkese Açık" if activity.visibility == "public" else "Sadece Arkadaşlar"
    )
    return {
        "id": activity.id,
        "title": activity.title,
        "date_label": format_plan_date_short(activity.date),
        "time_label": activity.time,
        "location": activity.location,
        "visibility_label": visibility_label,
        "category_key": key,
        "category_label": ACTIVITY_CATEGORY_LABELS.get(key, ""),
        "detail_url": url_for("activity_detail", activity_id=activity.id),
        "home_url": url_for("home"),
        "success_url": url_for("activity_created", activity_id=activity.id),
    }


def derive_display_handle(user):
    local_part = (user.email or "").split("@")[0].lower()
    safe = "".join(char for char in local_part if char.isalnum() or char == "_")
    return f"@{safe[:30] or 'user'}"


def turkish_possessive(name):
    name = (name or "").strip() or "Kullanıcı"
    last_vowel = None
    for char in reversed(name):
        folded = char.replace("İ", "i").replace("I", "ı").lower()
        if folded in "aeıioöuü":
            last_vowel = folded
            break
    if last_vowel in ("e", "i"):
        harmony = "i"
    elif last_vowel in ("a", "ı"):
        harmony = "ı"
    elif last_vowel in ("o", "u"):
        harmony = "u"
    elif last_vowel in ("ö", "ü"):
        harmony = "ü"
    else:
        harmony = "i"
    last_folded = name[-1].replace("İ", "i").replace("I", "ı").lower()
    suffix = f"n{harmony}n" if last_folded in "aeıioöuü" else f"{harmony}n"
    return f"{name}'{suffix}"


def format_profile_datetime(date_str, time_str):
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return f"{dt.day} {PROFILE_MONTHS[dt.month]} · {dt.strftime('%H:%M')}"
    except ValueError:
        return f"{date_str} {time_str}"


def count_joined_participants(activity):
    return sum(
        1 for participant in activity.participants if participant.status == "joined"
    )


def serialize_profile_activity(activity, *, is_past, source="profile", user_id=None):
    joined_count = count_joined_participants(activity)
    if is_past:
        participant_label = f"{joined_count} kişi katıldı"
    else:
        participant_label = f"{joined_count} kişi katılıyor"
    detail_kwargs = {
        "activity_id": activity.id,
        "source": source,
    }
    if source == "user_profile":
        profile_user_id = parse_user_profile_id(user_id)
        if profile_user_id is not None:
            detail_kwargs["user_id"] = profile_user_id
    creator = activity.creator
    category_key = _activity_category_key(activity)
    time_label, _time_is_today = format_activity_time_label(activity.date, activity.time)
    return {
        "id": activity.id,
        "title": activity.title,
        "datetime": format_profile_datetime(activity.date, activity.time),
        "time_label": time_label,
        "location": (activity.location or "").strip(),
        "cover_image": COVER_IMAGES[activity.id % len(COVER_IMAGES)],
        "joined_count": joined_count,
        "participant_label": participant_label,
        "visibility": activity.visibility,
        "visibility_label": VISIBILITY_LABELS.get(activity.visibility, "Herkese açık"),
        "is_past": is_past,
        "creator_name": display_first_name(creator.full_name if creator else ""),
        "creator_avatar": avatar_for_user(creator),
        "category_key": category_key,
        "category_label": ACTIVITY_CATEGORY_LABELS.get(category_key, "Diğer"),
        "created_label": format_created_ago_label(activity.created_at),
        "detail_url": url_for("activity_detail", **detail_kwargs),
    }


def activity_sort_key(activity):
    return parse_activity_datetime_local(activity.date, activity.time)


def partition_profile_activities(activities, source="profile", user_id=None):
    upcoming_raw = []
    past_raw = []
    for activity in activities:
        occurred = activity_has_occurred_or_skip(activity)
        if occurred is None:
            continue
        if occurred:
            past_raw.append(activity)
        else:
            upcoming_raw.append(activity)
    upcoming_raw.sort(key=activity_sort_key)
    past_raw.sort(key=activity_sort_key, reverse=True)
    return {
        "upcoming": [
            serialize_profile_activity(
                activity, is_past=False, source=source, user_id=user_id
            )
            for activity in upcoming_raw
        ],
        "past": [
            serialize_profile_activity(
                activity, is_past=True, source=source, user_id=user_id
            )
            for activity in past_raw
        ],
    }


EXPERIENCE_JOINED_STATUS = "joined"
EXPERIENCE_EMPTY_MESSAGE = "Henüz tamamlanmış sosyal deneyimin yok."
WHEEL_CX = 50
WHEEL_CY = 50
WHEEL_RADIUS = 40


def participation_qualifies_as_experience(status):
    return (status or "").strip() == EXPERIENCE_JOINED_STATUS


def select_joined_experience_activities(participations):
    selected = []
    seen = set()
    for item in participations or []:
        if item is None:
            continue
        if isinstance(item, tuple):
            activity = item[0] if item else None
            status = item[1] if len(item) > 1 else None
        else:
            activity = getattr(item, "activity", None)
            status = getattr(item, "status", None)
        if not participation_qualifies_as_experience(status):
            continue
        activity_id = getattr(activity, "id", None)
        if activity is None or activity_id is None or activity_id in seen:
            continue
        seen.add(activity_id)
        selected.append(activity)
    return selected


def activity_has_occurred_or_skip(activity):
    try:
        date_str = getattr(activity, "date", None)
        time_str = getattr(activity, "time", None)
        if not isinstance(date_str, str) or not isinstance(time_str, str):
            return None
        if not date_str.strip() or not time_str.strip():
            return None
        return is_activity_datetime_in_past(date_str, time_str)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None


def collect_completed_experience_activities(created_activities, joined_activities):
    by_id = {}
    for activity in list(created_activities or []) + list(joined_activities or []):
        activity_id = getattr(activity, "id", None)
        if activity is None or activity_id is None or activity_id in by_id:
            continue
        by_id[activity_id] = activity

    completed = []
    for activity in by_id.values():
        if activity_has_occurred_or_skip(activity) is True:
            completed.append(activity)
    return completed


def count_experiences_by_category(activities):
    counts = {key: 0 for key in ACTIVITY_CATEGORY_LABELS}
    for activity in activities or []:
        key = _activity_category_key(activity)
        if key not in counts:
            key = "diger"
        counts[key] += 1
    return {key: count for key, count in counts.items() if count > 0}


def allocate_display_percents(counts):
    items = [(key, count) for key, count in (counts or {}).items() if count > 0]
    if not items:
        return {}
    if len(items) == 1:
        return {items[0][0]: 100}

    total = sum(count for _, count in items)
    ranked = []
    percents = {}
    for index, (key, count) in enumerate(items):
        exact = count * 100 / total
        floor_value = int(exact)
        percents[key] = floor_value
        ranked.append((key, floor_value, exact - floor_value, index))

    remainder = 100 - sum(percents.values())
    ranked.sort(key=lambda item: (-item[2], item[3]))
    index = 0
    while remainder > 0 and ranked:
        percents[ranked[index][0]] += 1
        remainder -= 1
        index = (index + 1) % len(ranked)

    for key, _count in items:
        if percents[key] > 0:
            continue
        donor = max(
            percents,
            key=lambda candidate: percents[candidate] if candidate != key else -1,
        )
        if percents[donor] > 1:
            percents[donor] -= 1
            percents[key] = 1
    return percents


def experience_intensity(count, max_count):
    if max_count <= 0 or count <= 0:
        return "low"
    if count == max_count or count / max_count >= 0.85:
        return "high"
    if count / max_count >= 0.45:
        return "mid"
    return "low"


def wheel_point(deg, radius=WHEEL_RADIUS, cx=WHEEL_CX, cy=WHEEL_CY):
    radians = math.radians(deg)
    return (
        cx + radius * math.sin(radians),
        cy - radius * math.cos(radians),
    )


def wheel_sweep_degrees(category_count):
    if category_count <= 0:
        return 0
    if category_count == 1:
        return 332.0
    slice_span = 360.0 / category_count
    gap = min(28.0, max(14.0, slice_span * 0.32))
    sweep = slice_span - gap
    if sweep < 18.0:
        sweep = min(max(18.0, slice_span * 0.55), max(slice_span - 8.0, 12.0))
    return sweep


def build_wheel_arc_path(
    center_deg, sweep_deg, radius=WHEEL_RADIUS, cx=WHEEL_CX, cy=WHEEL_CY
):
    if sweep_deg <= 0:
        return ""
    start_deg = center_deg - (sweep_deg / 2)
    end_deg = center_deg + (sweep_deg / 2)
    x1, y1 = wheel_point(start_deg, radius, cx, cy)
    x2, y2 = wheel_point(end_deg, radius, cx, cy)
    large_arc = 1 if sweep_deg > 180 else 0
    return (
        f"M {x1:.2f} {y1:.2f} "
        f"A {radius} {radius} 0 {large_arc} 1 {x2:.2f} {y2:.2f}"
    )


def build_experience_sr_summary(total, categories):
    if total <= 0 or not categories:
        return EXPERIENCE_EMPTY_MESSAGE
    parts = [
        f"{item['label']} {item['count']} (%{item['percent']})"
        for item in categories
    ]
    return f"{total} tamamlanmış sosyal deneyim: " + ", ".join(parts) + "."


def build_experience_presentation(
    created_activities, joined_activities=None, participations=None
):
    joined = list(joined_activities or [])
    if participations is not None:
        joined.extend(select_joined_experience_activities(participations))

    completed = collect_completed_experience_activities(
        created_activities, joined
    )
    total = len(completed)
    if total == 0:
        return {
            "total": 0,
            "is_empty": True,
            "empty_message": EXPERIENCE_EMPTY_MESSAGE,
            "sr_summary": EXPERIENCE_EMPTY_MESSAGE,
            "categories": [],
        }

    counts = count_experiences_by_category(completed)
    percents = allocate_display_percents(counts)
    keys = list(counts.keys())
    category_count = len(keys)
    sweep = wheel_sweep_degrees(category_count)
    max_count = max(counts.values()) if counts else 0
    slice_span = 360.0 / category_count if category_count else 0

    categories = []
    for index, key in enumerate(keys):
        count = counts[key]
        percent = percents.get(key, 0)
        center_deg = slice_span * index
        categories.append(
            {
                "key": key,
                "label": ACTIVITY_CATEGORY_LABELS.get(key, "Diğer"),
                "count": count,
                "percent": percent,
                "intensity": experience_intensity(count, max_count),
                "angle": round(center_deg, 2),
                "arc_d": build_wheel_arc_path(center_deg, sweep),
            }
        )

    return {
        "total": total,
        "is_empty": False,
        "empty_message": EXPERIENCE_EMPTY_MESSAGE,
        "sr_summary": build_experience_sr_summary(total, categories),
        "categories": categories,
    }


def get_profile_context(user, viewer=None):
    first_name = user.full_name.split()[0] if user.full_name else "Kullanıcı"
    created_activities = Activity.query.filter_by(creator_id=user.id).all()
    joined_activities = (
        Activity.query.join(ActivityParticipant)
        .filter(
            ActivityParticipant.user_id == user.id,
            ActivityParticipant.status == "joined",
            Activity.creator_id != user.id,
        )
        .all()
    )
    detail_source = "profile"
    detail_user_id = None
    if viewer is not None and viewer.id != user.id:
        friend_ids = get_accepted_friend_ids(viewer.id)
        created_activities = [
            activity
            for activity in created_activities
            if can_view_activity(viewer, activity, friend_ids=friend_ids)
        ]
        joined_activities = [
            activity
            for activity in joined_activities
            if can_view_activity(viewer, activity, friend_ids=friend_ids)
        ]
        detail_source = "user_profile"
        detail_user_id = user.id
    friend_ids = get_accepted_friend_ids(user.id)
    return {
        "profile_user": {
            "first_name": first_name,
            "possessive_first_name": turkish_possessive(first_name),
            "handle": derive_display_handle(user),
            "bio": "Henüz biyografi eklenmedi.",
            "avatar": avatar_for_user(user),
        },
        "stats": {
            "created_count": len(created_activities),
            "joined_count": len(joined_activities),
            "friends_count": len(friend_ids),
        },
        "created": partition_profile_activities(
            created_activities, source=detail_source, user_id=detail_user_id
        ),
        "joined": partition_profile_activities(
            joined_activities, source=detail_source, user_id=detail_user_id
        ),
        "experience": build_experience_presentation(
            created_activities, joined_activities
        ),
    }


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


def format_comment_relative(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    seconds = int((now - dt).total_seconds())
    if seconds < 45:
        return "şimdi"
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} dk"
    if seconds < 86400:
        return f"{seconds // 3600} sa"
    if seconds < 172800:
        return "dün"
    days = seconds // 86400
    if days < 7:
        return f"{days} g"
    return format_comment_datetime(dt)


def render_activity_detail(
    activity,
    current_user=None,
    error=None,
    form_body="",
    detail_from="home",
    detail_q="",
    detail_filter="all",
    detail_user_id="",
    detail_time="all",
    detail_category="",
    detail_city="",
):
    from_page, q, activity_filter = parse_detail_context(
        detail_from, detail_q, detail_filter
    )
    profile_user_id = None
    if from_page == "user_profile":
        profile_user_id = parse_user_profile_id(detail_user_id)
        if profile_user_id is None:
            from_page = "home"
    back_url = build_list_back_url(
        from_page,
        q,
        activity_filter,
        user_id=profile_user_id,
        detail_time=detail_time,
        detail_category=detail_category,
        detail_city=detail_city,
    )
    joined_count = sum(1 for p in activity.participants if p.status == "joined")
    maybe_count = sum(1 for p in activity.participants if p.status == "maybe")
    friend_ids = (
        get_accepted_friend_ids(current_user.id) if current_user is not None else set()
    )
    participant_display = build_participant_display(
        activity,
        current_user.id if current_user is not None else 0,
        friend_ids,
    )
    maybe_people = [
        {
            "name": format_display_name(participant.user.full_name),
            "avatar": avatar_for_user(participant.user),
        }
        for participant in activity.participants
        if participant.status == "maybe"
    ]
    joined_people = [
        {
            "name": format_display_name(participant.user.full_name),
            "avatar": avatar_for_user(participant.user),
        }
        for participant in activity.participants
        if participant.status == "joined"
    ]
    maybe_avatars = [person["avatar"] for person in maybe_people[:4]]
    comments = (
        Comment.query.filter_by(activity_id=activity.id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    comment_items = [
        {
            "author_name": display_first_name(comment.user.full_name),
            "avatar": avatar_for_user(comment.user),
            "body": comment.body,
            "created_at": format_comment_relative(comment.created_at),
        }
        for comment in comments
    ]
    is_owner = (
        current_user is not None and is_activity_owner(current_user, activity)
    )
    time_label, _time_is_today = format_activity_time_label(activity.date, activity.time)

    category_key = _activity_category_key(activity)

    return render_template(
        "activity_detail.html",
        activity=activity,
        comments=comment_items,
        cover_image=COVER_IMAGES[activity.id % len(COVER_IMAGES)],
        datetime=format_activity_datetime(activity.date, activity.time),
        datetime_compact=format_activity_datetime_compact(activity.date, activity.time),
        time_label=time_label,
        category_key=category_key,
        category_label=ACTIVITY_CATEGORY_LABELS.get(category_key, ""),
        visibility_label=VISIBILITY_LABELS.get(activity.visibility, "Herkese açık"),
        joined_count=joined_count,
        maybe_count=maybe_count,
        participants_summary=participant_display["summary"],
        participants_lead_name=participant_display["lead_name"],
        participant_avatars=participant_display["avatars"],
        maybe_avatars=maybe_avatars,
        joined_people=joined_people,
        maybe_people=maybe_people,
        current_user_avatar=(
            avatar_for_user(current_user) if current_user is not None else None
        ),
        is_owner=is_owner,
        is_past=is_activity_datetime_in_past(activity.date, activity.time),
        error=error,
        form_body=form_body,
        comment_max_length=COMMENT_MAX_LENGTH,
        back_url=back_url,
        detail_from=from_page,
        detail_q=q,
        detail_filter=activity_filter,
        detail_user_id=profile_user_id or "",
        creator_profile_url=build_user_profile_url(
            activity.creator.id,
            from_activity_id=activity.id,
            from_page=from_page,
            q=q,
            activity_filter=activity_filter,
            detail_user_id=profile_user_id,
        ),
    )


@app.route("/")
def home():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friend_ids = get_accepted_friend_ids(current_user.id)
    time_filter = parse_time_filter(request.args.get("time"))
    category_filter = parse_category_filter(request.args.get("category"))

    query = Activity.query
    activities_db = query.order_by(Activity.date.asc(), Activity.time.asc()).all()
    activities = []
    for activity in activities_db:
        if is_activity_datetime_in_past(activity.date, activity.time):
            continue
        if not can_view_activity(current_user, activity, friend_ids=friend_ids):
            continue
        if not activity_matches_time_filter(activity, time_filter):
            continue
        time_label, time_is_today = format_activity_time_label(activity.date, activity.time)
        participant_display = build_participant_display(
            activity, current_user.id, friend_ids
        )
        category_key = _activity_category_key(activity)
        joined_count = participant_display["joined_count"]
        maybe_count = participant_display["maybe_count"]
        user_participation = next(
            (p for p in activity.participants if p.user_id == current_user.id),
            None,
        )
        creator_avatar = avatar_for_user(activity.creator)
        activities.append(
            {
                "id": activity.id,
                "creator_name": creator_avatar["name"],
                "creator_avatar": creator_avatar,
                "title": activity.title,
                "description": " ".join((activity.description or "").split()),
                "time_label": time_label,
                "time_is_today": time_is_today,
                "location": activity.location,
                "category_key": category_key,
                "joined_count": joined_count,
                "maybe_count": maybe_count,
                "participants_summary": participant_display["summary"],
                "participant_avatars": participant_display["avatars"],
                "user_status": user_participation.status if user_participation else None,
                "visibility": activity.visibility,
            }
        )

    first_name = display_first_name(current_user.full_name)
    user = {
        "name": first_name,
        "avatar": avatar_for_user(current_user),
    }

    has_active_search = time_filter != "all" or bool(category_filter)

    return render_template(
        "index.html",
        activities=activities,
        user=user,
        q="",
        activity_filter="all",
        time_filter=time_filter,
        category_filter=category_filter,
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
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    if error:
        if wants_json:
            return jsonify({"ok": False, "error": error}), 400
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
        category=form_data["category"],
        creator_id=current_user.id,
    )
    db.session.add(activity)
    db.session.commit()

    category_key = _activity_category_key(activity)
    created = build_created_plan_view(activity, category_key)
    if wants_json:
        return jsonify({"ok": True, **created})
    return redirect(url_for("activity_created", activity_id=activity.id))


@app.route("/create-activity/success/<int:activity_id>")
def activity_created(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    activity = db.session.get(Activity, activity_id)
    if activity is None or activity.creator_id != current_user.id:
        return redirect(url_for("home"))

    category_key = _activity_category_key(activity)
    created = build_created_plan_view(activity, category_key)
    return render_template("activity_created.html", created=created)


@app.route("/activity/<int:activity_id>/respond", methods=["POST"])
def respond_activity(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    status = request.form.get("status", "").strip()
    origin = request.form.get("origin", "home").strip()
    return_from = request.form.get("return_from", "home").strip()
    return_q = request.form.get("return_q", "").strip()
    return_filter = request.form.get("return_filter", "all").strip()
    return_user_id = request.form.get("return_user_id", "").strip()

    if status not in VALID_PARTICIPANT_STATUSES:
        return redirect_after_respond(
            activity_id,
            origin,
            return_from,
            return_q,
            return_filter,
            user_id=return_user_id,
        )

    activity = db.session.get(Activity, activity_id)
    if activity is None:
        return redirect(url_for("home"))

    if not can_view_activity(current_user, activity):
        return redirect(url_for("home"))

    if is_activity_datetime_in_past(activity.date, activity.time):
        return redirect_after_respond(
            activity_id,
            origin,
            return_from,
            return_q,
            return_filter,
            user_id=return_user_id,
        )

    participation = ActivityParticipant.query.filter_by(
        user_id=current_user.id,
        activity_id=activity_id,
    ).first()

    was_joined = participation is not None and participation.status == "joined"

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

    if (
        status == "joined"
        and not was_joined
        and current_user.id != activity.creator_id
    ):
        create_or_update_notification(
            recipient_id=activity.creator_id,
            type="activity_join",
            actor_id=current_user.id,
            activity_id=activity.id,
        )

    db.session.commit()
    return redirect_after_respond(
        activity_id,
        origin,
        return_from,
        return_q,
        return_filter,
        user_id=return_user_id,
    )


@app.route("/activity/<int:activity_id>")
def activity_detail(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    friend_ids = get_accepted_friend_ids(current_user.id)
    activity = get_viewable_activity(activity_id, current_user, friend_ids=friend_ids)
    if activity is None:
        return redirect(url_for("home"))

    return render_activity_detail(
        activity,
        current_user=current_user,
        detail_from=request.args.get("source", ""),
        detail_q=request.args.get("q", ""),
        detail_filter=request.args.get("filter", "all"),
        detail_user_id=request.args.get("user_id", ""),
        detail_time=parse_discover_time_filter(request.args.get("time")),
        detail_category=parse_category_filter(request.args.get("category")),
        detail_city=parse_discover_city_filter(request.args.get("city")),
    )


@app.route("/activity/<int:activity_id>/edit", methods=["GET", "POST"])
def edit_activity(activity_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    activity = get_editable_activity(activity_id, current_user)
    if activity is None:
        return redirect(url_for("home"))

    if request.method == "GET":
        category_key = _activity_category_key(activity)
        form_data = {
            "title": activity.title,
            "description": activity.description,
            "date": activity.date,
            "time": activity.time,
            "location": activity.location,
            "visibility": activity.visibility,
            "category": category_key,
        }
        today = datetime.now(TURKEY_TZ).strftime("%Y-%m-%d")
        min_date = activity.date if activity.date and activity.date < today else today
        return render_template(
            "create_activity.html",
            activity=activity,
            form_data=form_data,
            min_date=min_date,
            is_edit=True,
        )

    form_data = parse_activity_form()
    form_data["category"] = request.form.get("category", "").strip()
    error = validate_activity_form(
        form_data,
        original_date=activity.date,
        original_time=activity.time,
    )
    today = datetime.now(TURKEY_TZ).strftime("%Y-%m-%d")
    min_date = activity.date if activity.date and activity.date < today else today
    if error:
        return render_template(
            "create_activity.html",
            activity=activity,
            form_data=form_data,
            error=error,
            min_date=min_date,
            is_edit=True,
        )

    old_date = activity.date
    old_time = activity.time

    activity.title = form_data["title"]
    activity.description = form_data["description"]
    activity.date = form_data["date"]
    activity.time = form_data["time"]
    activity.location = form_data["location"]
    activity.visibility = form_data["visibility"]
    activity.category = form_data["category"]

    date_changed = form_data["date"] != old_date
    time_changed = form_data["time"] != old_time
    if date_changed or time_changed:
        time_change_fields = {}
        if time_changed:
            time_change_fields["old_time"] = old_time
            time_change_fields["new_time"] = form_data["time"]
        if date_changed:
            time_change_fields["old_date"] = old_date
            time_change_fields["new_date"] = form_data["date"]

        participants = ActivityParticipant.query.filter(
            ActivityParticipant.activity_id == activity.id,
            ActivityParticipant.status.in_(("joined", "maybe")),
            ActivityParticipant.user_id != activity.creator_id,
        ).all()
        for participant in participants:
            create_or_update_notification(
                recipient_id=participant.user_id,
                type="activity_time_change",
                actor_id=activity.creator_id,
                activity_id=activity.id,
                **time_change_fields,
            )

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
    return_from = request.form.get("return_from", "home").strip()
    return_q = request.form.get("return_q", "").strip()
    return_filter = request.form.get("return_filter", "all").strip()
    return_user_id = request.form.get("return_user_id", "").strip()

    if not body:
        return render_activity_detail(
            activity,
            current_user=current_user,
            error="Lütfen bir yorum yazın.",
            form_body="",
            detail_from=return_from,
            detail_q=return_q,
            detail_filter=return_filter,
            detail_user_id=return_user_id,
        )

    if len(body) > COMMENT_MAX_LENGTH:
        return render_activity_detail(
            activity,
            current_user=current_user,
            error=f"Yorum en fazla {COMMENT_MAX_LENGTH} karakter olabilir.",
            form_body=body[:COMMENT_MAX_LENGTH],
            detail_from=return_from,
            detail_q=return_q,
            detail_filter=return_filter,
            detail_user_id=return_user_id,
        )

    comment = Comment(
        user_id=current_user.id,
        activity_id=activity_id,
        body=body,
    )
    db.session.add(comment)

    if current_user.id != activity.creator_id:
        db.session.flush()
        create_or_update_notification(
            recipient_id=activity.creator_id,
            type="activity_comment",
            actor_id=current_user.id,
            activity_id=activity.id,
            comment_id=comment.id,
        )

    db.session.commit()
    from_page, q, activity_filter = parse_detail_context(
        return_from, return_q, return_filter
    )
    return redirect(
        build_detail_url(
            activity_id,
            from_page,
            q,
            activity_filter,
            user_id=return_user_id,
        )
    )

def _activity_category_key(activity):
    key = (activity.category or "").strip()
    return key if key in ACTIVITY_CATEGORY_LABELS else "diger"


def _discover_activity_card(activity, search_q=""):
    creator_avatar = avatar_for_user(activity.creator)
    time_label, _time_is_today = format_activity_time_label(activity.date, activity.time)
    joined_count = sum(1 for p in activity.participants if p.status == "joined")
    category_key = _activity_category_key(activity)
    detail_kwargs = {"activity_id": activity.id, "source": "discover"}
    if search_q:
        detail_kwargs["q"] = search_q
    return {
        "id": activity.id,
        "title": activity.title,
        "time_label": time_label,
        "location": activity.location or "",
        "creator_name": format_short_display_name(activity.creator.full_name),
        "creator_avatar": creator_avatar,
        "joined_count": joined_count,
        "category_key": category_key,
        "category_label": ACTIVITY_CATEGORY_LABELS.get(category_key, "Diğer"),
        "detail_url": url_for("activity_detail", **detail_kwargs),
        "created_at": activity.created_at or datetime.min,
        "date": activity.date,
        "time": activity.time,
    }


def _discover_suggestion_reason(activity):
    today = datetime.now(TURKEY_TZ).date()
    try:
        activity_date = datetime.strptime(activity.date, "%Y-%m-%d").date()
    except ValueError:
        return "Yakında katılabileceğin herkese açık bir plan"
    if activity_date == today:
        return "Bugün katılabileceğin herkese açık bir plan"
    if activity_date == today + timedelta(days=1):
        return "Yarın katılabileceğin herkese açık bir plan"
    return "Yakında katılabileceğin herkese açık bir plan"


def _user_joined_activity_ids(user_id):
    rows = ActivityParticipant.query.filter_by(user_id=user_id, status="joined").all()
    return {row.activity_id for row in rows}


def _parse_activity_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _shared_joined_activities(user_a_id, user_b_id):
    shared_ids = _user_joined_activity_ids(user_a_id) & _user_joined_activity_ids(user_b_id)
    if not shared_ids:
        return []
    activities = Activity.query.filter(Activity.id.in_(shared_ids)).all()
    activities.sort(
        key=lambda activity: (
            _parse_activity_date(activity.date) or datetime.min.date(),
            activity.time or "",
        ),
        reverse=True,
    )
    return activities


def _count_mutual_friends(user_a_id, user_b_id):
    friends_a = get_accepted_friend_ids(user_a_id)
    friends_b = get_accepted_friend_ids(user_b_id)
    return len(friends_a & friends_b)


def _user_joined_in_month(user_id, year, month):
    participants = ActivityParticipant.query.filter_by(
        user_id=user_id, status="joined"
    ).all()
    for participant in participants:
        activity_date = _parse_activity_date(participant.activity.date)
        if activity_date and activity_date.year == year and activity_date.month == month:
            return True
    return False


def _user_joined_since(user_id, since_date):
    participants = ActivityParticipant.query.filter_by(
        user_id=user_id, status="joined"
    ).all()
    for participant in participants:
        activity_date = _parse_activity_date(participant.activity.date)
        if activity_date and activity_date >= since_date:
            return True
    return False


def _user_public_activity_count(user_id):
    return Activity.query.filter_by(creator_id=user_id, visibility="public").count()


def _pick_friend_suggestion_reason(current_user_id, other_user_id):
    shared_activities = _shared_joined_activities(current_user_id, other_user_id)
    if shared_activities:
        title = shared_activities[0].title.strip()
        if len(title) > 48:
            title = f"{title[:45].rstrip()}..."
        return {
            "priority": 1000,
            "icon": "event",
            "text": f"Aynı {title} etkinliğine katıldınız",
        }

    today = datetime.now(TURKEY_TZ).date()
    if _user_joined_in_month(current_user_id, today.year, today.month) and _user_joined_in_month(
        other_user_id, today.year, today.month
    ):
        return {
            "priority": 800,
            "icon": "calendar",
            "text": "Bu ay benzer etkinliklere katıldınız",
        }

    since = today - timedelta(days=30)
    if _user_joined_since(current_user_id, since) and _user_joined_since(other_user_id, since):
        return {
            "priority": 750,
            "icon": "spark",
            "text": "Son zamanlarda benzer ilgi alanlarında aktifsiniz",
        }

    mutual_count = _count_mutual_friends(current_user_id, other_user_id)
    if mutual_count > 0:
        return {
            "priority": 400 + min(mutual_count, 10),
            "icon": "mutual",
            "text": f"{mutual_count} ortak arkadaşınız var",
        }

    if _user_public_activity_count(other_user_id) > 0:
        return {
            "priority": 300,
            "icon": "spark",
            "text": "Herkese açık planlar paylaşıyor",
        }

    return {
        "priority": 100,
        "icon": "spark",
        "text": "VESİLE topluluğunda tanışabileceğin biri",
    }


def _build_friend_suggestion_card(other, current_user, search_q="", list_source="discover"):
    friendship = get_friendship(current_user.id, other.id)
    state = friendship_ui_state(current_user.id, other.id, friendship)
    reason = _pick_friend_suggestion_reason(current_user.id, other.id)
    profile_kwargs = {"user_id": other.id, "source": list_source}
    if search_q:
        profile_kwargs["q"] = search_q
    return {
        "user_id": other.id,
        "name": format_short_display_name(other.full_name),
        "avatar": avatar_for_user(other),
        "bio": "Henüz biyografi eklenmedi.",
        "interests": [],
        "reason_text": reason["text"],
        "reason_icon": reason["icon"],
        "reason_priority": reason["priority"],
        "state": state,
        "profile_url": url_for("user_profile", **profile_kwargs),
    }


def get_discover_friend_suggestions(current_user, search_q="", limit=None):
    friend_ids = get_accepted_friend_ids(current_user.id)
    query = User.query.filter(User.id != current_user.id)
    if search_q:
        query = query.filter(User.full_name.ilike(f"%{search_q}%"))
    other_users = query.all()

    cards = []
    for other in other_users:
        if other.id in friend_ids:
            continue
        friendship = get_friendship(current_user.id, other.id)
        state = friendship_ui_state(current_user.id, other.id, friendship)
        if state not in ("add", "sent"):
            continue
        cards.append(
            _build_friend_suggestion_card(
                other,
                current_user,
                search_q=search_q,
                list_source="discover_people" if limit is None else "discover",
            )
        )

    cards.sort(
        key=lambda card: (-card["reason_priority"], card["name"].casefold()),
    )
    if limit is not None:
        cards = cards[:limit]
    return cards


def _discover_upcoming_list_card(
    activity,
    search_q="",
    time_filter="all",
    category_filter="",
    city_filter="",
):
    creator_avatar = avatar_for_user(activity.creator)
    time_label, _time_is_today = format_activity_time_label(activity.date, activity.time)
    when_parts = format_upcoming_when_parts(activity.date, activity.time)
    joined = [p for p in activity.participants if p.status == "joined"]
    joined_count = len(joined)
    participant_avatars = [avatar_for_user(p.user) for p in joined[:3]]
    category_key = _activity_category_key(activity)
    comment_count = Comment.query.filter_by(activity_id=activity.id).count()
    detail_url = build_detail_url(
        activity.id,
        "discover_upcoming",
        q=search_q,
        time_filter=time_filter,
        category_filter=category_filter,
        city_filter=city_filter,
    )
    return {
        "id": activity.id,
        "title": activity.title,
        "time_label": time_label,
        "day_label": when_parts["day_label"],
        "clock_label": when_parts["clock_label"],
        "date_label": when_parts["date_label"],
        "time_is_today": when_parts["is_today"],
        "location": activity.location or "",
        "creator_name": format_short_display_name(activity.creator.full_name),
        "creator_avatar": creator_avatar,
        "joined_count": joined_count,
        "participant_avatars": participant_avatars,
        "comment_count": comment_count,
        "category_key": category_key,
        "category_label": ACTIVITY_CATEGORY_LABELS.get(category_key, "Diğer"),
        "detail_url": detail_url,
    }


def _discover_recent_list_card(
    activity,
    search_q="",
    category_filter="",
    city_filter="",
):
    creator_avatar = avatar_for_user(activity.creator)
    time_label, _time_is_today = format_activity_time_label(activity.date, activity.time)
    joined = [p for p in activity.participants if p.status == "joined"]
    joined_count = len(joined)
    participant_avatars = [avatar_for_user(p.user) for p in joined[:3]]
    category_key = _activity_category_key(activity)
    comment_count = Comment.query.filter_by(activity_id=activity.id).count()
    detail_url = build_detail_url(
        activity.id,
        "discover_recent",
        q=search_q,
        category_filter=category_filter,
        city_filter=city_filter,
    )
    return {
        "id": activity.id,
        "title": activity.title,
        "time_label": time_label,
        "location": activity.location or "",
        "creator_name": format_short_display_name(activity.creator.full_name),
        "creator_avatar": creator_avatar,
        "joined_count": joined_count,
        "participant_avatars": participant_avatars,
        "comment_count": comment_count,
        "added_label": format_added_ago_label(activity.created_at),
        "category_key": category_key,
        "category_label": ACTIVITY_CATEGORY_LABELS.get(category_key, "Diğer"),
        "detail_url": detail_url,
    }


def _build_upcoming_active_filters(
    q="",
    time_filter="all",
    category_filter="",
    city_filter="",
):
    filters = []

    if city_filter:
        filters.append(
            {
                "key": "city",
                "label": city_filter,
                "remove_url": build_discover_upcoming_url(
                    q, time_filter, category_filter, ""
                ),
            }
        )
    if time_filter != "all":
        filters.append(
            {
                "key": "time",
                "label": UPCOMING_LIST_TIME_FILTER_LABELS.get(time_filter, time_filter),
                "remove_url": build_discover_upcoming_url(
                    q, "all", category_filter, city_filter
                ),
            }
        )
    if category_filter:
        filters.append(
            {
                "key": "category",
                "label": ACTIVITY_CATEGORY_LABELS.get(category_filter, category_filter),
                "remove_url": build_discover_upcoming_url(
                    q, time_filter, "", city_filter
                ),
            }
        )
    return filters


def _build_recent_active_filters(
    q="",
    category_filter="",
    city_filter="",
):
    filters = []

    if city_filter:
        filters.append(
            {
                "key": "city",
                "label": city_filter,
                "remove_url": build_discover_recent_url(
                    q, category_filter, ""
                ),
            }
        )
    if category_filter:
        filters.append(
            {
                "key": "category",
                "label": ACTIVITY_CATEGORY_LABELS.get(category_filter, category_filter),
                "remove_url": build_discover_recent_url(
                    q, "", city_filter
                ),
            }
        )
    return filters


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
    upcoming_source = []
    for activity in activities_db:
        if is_activity_datetime_in_past(activity.date, activity.time):
            continue
        upcoming_source.append(activity)

    upcoming_events = [
        _discover_activity_card(activity, search_q) for activity in upcoming_source[:8]
    ]

    recent_source = sorted(
        upcoming_source,
        key=lambda activity: activity.created_at or datetime.min,
        reverse=True,
    )
    recent_events = [
        _discover_activity_card(activity, search_q) for activity in recent_source[:8]
    ]

    today = datetime.now(TURKEY_TZ).date()

    def suggestion_sort_key(activity):
        try:
            activity_date = datetime.strptime(activity.date, "%Y-%m-%d").date()
        except ValueError:
            activity_date = today + timedelta(days=365)
        is_today = 0 if activity_date == today else 1
        return (is_today, activity_sort_key(activity))

    suggestion_source = sorted(upcoming_source, key=suggestion_sort_key)[:3]
    today_picks = []
    for activity in suggestion_source:
        card = _discover_activity_card(activity, search_q)
        card["reason"] = _discover_suggestion_reason(activity)
        card["description"] = " ".join((activity.description or "").split())
        today_picks.append(card)

    friend_suggestions = get_discover_friend_suggestions(
        current_user, search_q=search_q, limit=8
    )

    return render_template(
        "discover.html",
        q=search_q,
        upcoming_events=upcoming_events,
        friend_suggestions=friend_suggestions,
        recent_events=recent_events,
        today_picks=today_picks,
    )


@app.route("/discover/upcoming")
def discover_upcoming():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    search_q = request.args.get("q", "").strip()
    time_filter = parse_upcoming_list_time_filter(request.args.get("time"))
    category_filter = parse_category_filter(request.args.get("category"))
    city_filter = parse_discover_city_filter(request.args.get("city"))

    query = Activity.query.filter(Activity.visibility == "public")
    if search_q:
        query = query.filter(Activity.title.ilike(f"%{search_q}%"))
    if city_filter:
        query = query.filter(Activity.location.ilike(f"%{city_filter}%"))

    activities_db = query.order_by(Activity.date.asc(), Activity.time.asc()).all()
    events = []
    for activity in activities_db:
        if is_activity_datetime_in_past(activity.date, activity.time):
            continue
        if not activity_matches_upcoming_list_time_filter(activity, time_filter):
            continue
        activity_category = _activity_category_key(activity)
        if category_filter and activity_category != category_filter:
            continue
        events.append(
            _discover_upcoming_list_card(
                activity,
                search_q=search_q,
                time_filter=time_filter,
                category_filter=category_filter,
                city_filter=city_filter,
            )
        )

    active_filters = _build_upcoming_active_filters(
        search_q, time_filter, category_filter, city_filter
    )
    has_active_filters = bool(active_filters)

    return render_template(
        "discover_upcoming.html",
        q=search_q,
        time_filter=time_filter,
        category_filter=category_filter,
        city_filter=city_filter,
        selected_city=city_filter or DEFAULT_DISCOVER_CITY,
        events=events,
        event_count=len(events),
        active_filters=active_filters,
        has_active_filters=has_active_filters,
        clear_filters_url=url_for("discover_upcoming", q=search_q or None),
        turkey_cities=TURKEY_CITIES,
        category_labels=ACTIVITY_CATEGORY_LABELS,
        time_filter_labels=UPCOMING_LIST_TIME_FILTER_LABELS,
        back_url=url_for("discover", q=search_q) if search_q else url_for("discover"),
    )


@app.route("/discover/recent")
def discover_recent():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    search_q = request.args.get("q", "").strip()
    category_filter = parse_category_filter(request.args.get("category"))
    city_filter = parse_discover_city_filter(request.args.get("city"))

    query = Activity.query.filter(Activity.visibility == "public")
    if search_q:
        query = query.filter(Activity.title.ilike(f"%{search_q}%"))
    if city_filter:
        query = query.filter(Activity.location.ilike(f"%{city_filter}%"))

    activities_db = query.all()
    matched = []
    for activity in activities_db:
        activity_category = _activity_category_key(activity)
        if category_filter and activity_category != category_filter:
            continue
        matched.append(activity)

    matched.sort(key=lambda activity: activity.created_at or datetime.min, reverse=True)
    events = [
        _discover_recent_list_card(
            activity,
            search_q=search_q,
            category_filter=category_filter,
            city_filter=city_filter,
        )
        for activity in matched
    ]

    active_filters = _build_recent_active_filters(
        search_q, category_filter, city_filter
    )
    has_active_filters = bool(active_filters)

    return render_template(
        "discover_recent.html",
        q=search_q,
        category_filter=category_filter,
        city_filter=city_filter,
        selected_city=city_filter or DEFAULT_DISCOVER_CITY,
        events=events,
        event_count=len(events),
        active_filters=active_filters,
        has_active_filters=has_active_filters,
        clear_filters_url=url_for("discover_recent", q=search_q or None),
        turkey_cities=TURKEY_CITIES,
        category_labels=ACTIVITY_CATEGORY_LABELS,
        back_url=url_for("discover", q=search_q) if search_q else url_for("discover"),
    )


@app.route("/discover/people")
def discover_people():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    search_q = request.args.get("q", "").strip()
    suggestions = get_discover_friend_suggestions(current_user, search_q=search_q)

    return render_template(
        "discover_people.html",
        q=search_q,
        suggestions=suggestions,
        person_count=len(suggestions),
        back_url=url_for("discover", q=search_q) if search_q else url_for("discover"),
    )


@app.route("/profile")
def profile():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    context = get_profile_context(current_user)
    return render_template("profile.html", **context)


@app.route("/settings")
def settings():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    return render_template("settings.html")


@app.route("/users/<int:user_id>")
def user_profile(user_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    if user_id == current_user.id:
        return redirect(url_for("profile"))

    viewed_user = db.session.get(User, user_id)
    if viewed_user is None:
        return redirect(url_for("home"))

    friendship = get_friendship(current_user.id, viewed_user.id)
    friendship_state = friendship_ui_state(
        current_user.id, viewed_user.id, friendship
    )
    context = get_profile_context(viewed_user, viewer=current_user)

    from_activity = parse_user_profile_id(request.args.get("from_activity"))
    from_page, q, activity_filter = parse_detail_context(
        request.args.get("source", ""),
        request.args.get("q", ""),
        request.args.get("filter", "all"),
    )
    nested_profile_id = parse_user_profile_id(request.args.get("detail_user_id"))
    if from_activity is None:
        back_url = build_list_back_url(
            from_page, q, activity_filter, user_id=nested_profile_id
        )
    else:
        back_url = build_detail_url(
            from_activity,
            from_page,
            q,
            activity_filter,
            user_id=nested_profile_id,
        )

    return render_template(
        "user_profile.html",
        viewed_user=viewed_user,
        friendship=friendship,
        friendship_state=friendship_state,
        back_url=back_url,
        from_activity=from_activity or "",
        detail_from=from_page,
        detail_q=q,
        detail_filter=activity_filter,
        detail_user_id=nested_profile_id or "",
        **context,
    )


@app.route("/notifications")
def notifications():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    notification_rows = (
        Notification.query.filter_by(
            recipient_id=current_user.id,
            is_dismissed=False,
        )
        .options(
            joinedload(Notification.actor),
            joinedload(Notification.activity),
            joinedload(Notification.friendship),
            joinedload(Notification.comment),
        )
        .order_by(Notification.created_at.desc())
        .all()
    )
    notifications = []
    for notification in notification_rows:
        notification.relative_time = format_relative_time(notification.created_at)
        notifications.append(notification)

    return render_template("notifications.html", notifications=notifications)


ACTIVITY_NOTIFICATION_TYPES = (
    "activity_join",
    "activity_comment",
    "activity_time_change",
)


@app.route("/notifications/<int:notification_id>/open")
def open_notification(notification_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.recipient_id != current_user.id:
        return redirect(url_for("notifications"))

    if notification.type in ACTIVITY_NOTIFICATION_TYPES:
        if not notification.activity_id:
            return redirect(url_for("notifications"))
        if not notification.is_read:
            notification.is_read = True
            db.session.commit()
        return redirect(
            url_for(
                "activity_detail",
                activity_id=notification.activity_id,
                source="notifications",
            )
        )

    if notification.type in ("friend_request", "friend_accept"):
        if not notification.actor_id:
            return redirect(url_for("notifications"))
        if not notification.is_read:
            notification.is_read = True
            db.session.commit()
        return redirect(
            url_for(
                "user_profile",
                user_id=notification.actor_id,
                source="notifications",
            )
        )

    return redirect(url_for("notifications"))


@app.route("/friend-list")
def friend_list():
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    me = current_user.id

    accepted = Friendship.query.filter(
        Friendship.status == "accepted",
        db.or_(Friendship.sender_id == me, Friendship.receiver_id == me),
    ).order_by(Friendship.updated_at.desc()).all()

    friends = []
    for friendship in accepted:
        other = (
            friendship.receiver
            if friendship.sender_id == me
            else friendship.sender
        )
        friends.append(
            {
                "user": other,
                "friendship_id": friendship.id,
            }
        )

    return render_template(
        "friend_list.html",
        friends=friends,
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
        state = friendship_ui_state(me, other.id, friendship)
        if state in ("incoming", "friends"):
            continue
        users.append(
            {
                "user": other,
                "friendship_id": friendship.id if friendship else None,
                "state": state,
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
    next_page = request.form.get("next", "friends").strip()
    if next_page not in ("user_profile", "discover", "discover_people"):
        next_page = "friends"

    def redirect_after_friend_request():
        if next_page == "user_profile":
            form_user_id = request.form.get("user_id", type=int)
            if form_user_id == user_id:
                return redirect(user_profile_url_from_values(user_id, request.form))
        if next_page == "discover_people":
            search_q = (request.form.get("q") or "").strip()
            if search_q:
                return redirect(url_for("discover_people", q=search_q))
            return redirect(url_for("discover_people"))
        if next_page == "discover":
            search_q = (request.form.get("q") or "").strip()
            if search_q:
                return redirect(url_for("discover", q=search_q))
            return redirect(url_for("discover"))
        return redirect(url_for("friends"))

    if other is None:
        return redirect(url_for("friends"))

    friendship = get_friendship(current_user.id, user_id)
    should_notify = False
    if friendship is None:
        friendship = Friendship(
            sender_id=current_user.id,
            receiver_id=user_id,
            status="pending",
        )
        db.session.add(friendship)
        db.session.flush()
        should_notify = True
    elif friendship.status == "rejected":
        friendship.sender_id = current_user.id
        friendship.receiver_id = user_id
        friendship.status = "pending"
        friendship.updated_at = datetime.utcnow()
        should_notify = True
    # pending or accepted -> no-op

    if should_notify:
        create_or_update_notification(
            recipient_id=friendship.receiver_id,
            type="friend_request",
            actor_id=friendship.sender_id,
            friendship_id=friendship.id,
        )

    db.session.commit()
    return redirect_after_friend_request()


def _redirect_after_friend_response(friendship=None):
    next_page = (request.form.get("next") or "friends").strip()
    if next_page == "notifications":
        return redirect(url_for("notifications"))
    if next_page == "user_profile" and friendship is not None:
        form_user_id = request.form.get("user_id", type=int)
        current_user = get_current_user()
        other_user_id = None
        if current_user is not None:
            if current_user.id == friendship.sender_id:
                other_user_id = friendship.receiver_id
            elif current_user.id == friendship.receiver_id:
                other_user_id = friendship.sender_id
        if form_user_id is not None and form_user_id == other_user_id:
            return redirect(
                user_profile_url_from_values(other_user_id, request.form)
            )
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
        return _redirect_after_friend_response()

    friendship.status = "accepted"
    friendship.updated_at = datetime.utcnow()

    notification = Notification.query.filter_by(
        recipient_id=current_user.id,
        friendship_id=friendship_id,
        type="friend_request",
    ).first()
    if notification is not None:
        notification.is_read = True

    create_or_update_notification(
        recipient_id=friendship.sender_id,
        type="friend_accept",
        actor_id=current_user.id,
        friendship_id=friendship.id,
    )

    db.session.commit()
    return _redirect_after_friend_response(friendship)


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
        return _redirect_after_friend_response()

    friendship.status = "rejected"
    friendship.updated_at = datetime.utcnow()

    notification = Notification.query.filter_by(
        recipient_id=current_user.id,
        friendship_id=friendship_id,
        type="friend_request",
    ).first()
    if notification is not None:
        now = _utc_now_naive()
        notification.is_read = True
        notification.is_dismissed = True
        notification.dismissed_at = now

    db.session.commit()
    return _redirect_after_friend_response(friendship)

@app.route("/friends/cancel/<int:friendship_id>", methods=["POST"])
def friends_cancel(friendship_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    next_page = request.form.get("next", "friends").strip()
    if next_page != "user_profile":
        next_page = "friends"
    form_user_id = request.form.get("user_id", type=int)

    friendship = db.session.get(Friendship, friendship_id)
    if (
        friendship is None
        or friendship.status != "pending"
        or friendship.sender_id != current_user.id
    ):
        return redirect(url_for("friends"))

    return_user_id = None
    if next_page == "user_profile" and form_user_id == friendship.receiver_id:
        return_user_id = friendship.receiver_id

    notification = Notification.query.filter_by(
        recipient_id=friendship.receiver_id,
        friendship_id=friendship.id,
        type="friend_request",
    ).first()
    if notification is not None:
        now = _utc_now_naive()
        notification.is_dismissed = True
        notification.dismissed_at = now
        notification.is_read = True

    db.session.delete(friendship)
    db.session.commit()
    if return_user_id is not None:
        return redirect(user_profile_url_from_values(return_user_id, request.form))
    return redirect(url_for("friends"))

@app.route("/friends/remove/<int:friendship_id>", methods=["POST"])
def friends_remove(friendship_id):
    current_user = get_current_user()
    if current_user is None:
        return redirect(url_for("login"))

    next_page = (request.form.get("next") or "friends").strip()
    if next_page == "friend_list":
        return_endpoint = "friend_list"
    elif next_page == "user_profile":
        return_endpoint = "friends"
    else:
        next_page = "friends"
        return_endpoint = "friends"

    form_user_id = request.form.get("user_id", type=int)

    friendship = db.session.get(Friendship, friendship_id)
    if (
        friendship is None
        or friendship.status != "accepted"
        or current_user.id not in (friendship.sender_id, friendship.receiver_id)
    ):
        return redirect(url_for(return_endpoint))

    other_user_id = (
        friendship.receiver_id
        if friendship.sender_id == current_user.id
        else friendship.sender_id
    )
    return_to_profile = (
        next_page == "user_profile" and form_user_id == other_user_id
    )

    db.session.delete(friendship)
    db.session.commit()
    if return_to_profile:
        return redirect(user_profile_url_from_values(other_user_id, request.form))
    return redirect(url_for(return_endpoint))

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
