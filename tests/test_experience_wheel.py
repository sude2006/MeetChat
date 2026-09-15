import re
import unittest
from types import SimpleNamespace

from app import (
    EXPERIENCE_EMPTY_MESSAGE,
    allocate_display_percents,
    build_experience_presentation,
    build_wheel_arc_path,
    collect_completed_experience_activities,
    count_experiences_by_category,
    select_joined_experience_activities,
    wheel_sweep_degrees,
)


PAST_DATE = "2000-01-15"
PAST_TIME = "14:30"
FUTURE_DATE = "2099-06-01"
FUTURE_TIME = "19:00"


def make_activity(activity_id, date, time, category="kahve"):
    return SimpleNamespace(id=activity_id, date=date, time=time, category=category)


class ExperienceWheelTests(unittest.TestCase):
    def test_created_past_plan_counts(self):
        created = [make_activity(1, PAST_DATE, PAST_TIME, "kahve")]
        result = build_experience_presentation(created, [])
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["is_empty"])
        self.assertEqual(result["categories"][0]["key"], "kahve")
        self.assertEqual(result["categories"][0]["count"], 1)

    def test_created_future_plan_does_not_count(self):
        created = [make_activity(1, FUTURE_DATE, FUTURE_TIME, "kahve")]
        result = build_experience_presentation(created, [])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["is_empty"])

    def test_past_joined_plan_counts(self):
        joined = [make_activity(2, PAST_DATE, PAST_TIME, "spor")]
        result = build_experience_presentation([], joined)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["categories"][0]["key"], "spor")

    def test_future_joined_plan_does_not_count(self):
        joined = [make_activity(2, FUTURE_DATE, FUTURE_TIME, "spor")]
        result = build_experience_presentation([], joined)
        self.assertEqual(result["total"], 0)

    def test_past_maybe_plan_does_not_count(self):
        maybe_plan = make_activity(3, PAST_DATE, PAST_TIME, "kitap")
        joined = select_joined_experience_activities([(maybe_plan, "maybe")])
        result = build_experience_presentation([], joined, participations=[
            (maybe_plan, "maybe")
        ])
        self.assertEqual(joined, [])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["is_empty"])

    def test_same_plan_from_creator_and_joined_counts_once(self):
        plan = make_activity(4, PAST_DATE, PAST_TIME, "doga")
        result = build_experience_presentation([plan], [plan])
        self.assertEqual(result["total"], 1)
        completed = collect_completed_experience_activities([plan], [plan])
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].id, 4)

    def test_multiple_categories_are_grouped_in_label_order(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "kitap"),
            make_activity(2, PAST_DATE, PAST_TIME, "kahve"),
            make_activity(3, PAST_DATE, PAST_TIME, "kitap"),
        ]
        joined = [make_activity(4, PAST_DATE, PAST_TIME, "spor")]
        result = build_experience_presentation(created, joined)
        keys = [item["key"] for item in result["categories"]]
        self.assertEqual(keys, ["kahve", "spor", "kitap"])
        counts = {item["key"]: item["count"] for item in result["categories"]}
        self.assertEqual(counts, {"kahve": 1, "spor": 1, "kitap": 2})
        self.assertEqual(result["total"], 4)

    def test_blank_and_unknown_categories_become_diger(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, ""),
            make_activity(2, PAST_DATE, PAST_TIME, "uzay"),
            make_activity(3, PAST_DATE, PAST_TIME, None),
        ]
        grouped = count_experiences_by_category(
            collect_completed_experience_activities(created, [])
        )
        self.assertEqual(grouped, {"diger": 3})
        result = build_experience_presentation(created, [])
        self.assertEqual(result["categories"][0]["key"], "diger")
        self.assertEqual(result["categories"][0]["label"], "Diğer")
        self.assertEqual(result["categories"][0]["count"], 3)

    def test_invalid_datetime_is_skipped_without_raising(self):
        created = [
            make_activity(1, "not-a-date", PAST_TIME, "kahve"),
            make_activity(2, PAST_DATE, "25:99", "spor"),
            make_activity(3, None, PAST_TIME, "kitap"),
            SimpleNamespace(id=4, date="", time="", category="doga"),
            make_activity(5, PAST_DATE, PAST_TIME, "kahve"),
        ]
        result = build_experience_presentation(created, [])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["categories"][0]["key"], "kahve")

    def test_empty_state_has_zero_total(self):
        result = build_experience_presentation([], [])
        self.assertEqual(result["total"], 0)
        self.assertTrue(result["is_empty"])
        self.assertEqual(result["categories"], [])
        self.assertEqual(result["empty_message"], EXPERIENCE_EMPTY_MESSAGE)
        self.assertEqual(result["sr_summary"], EXPERIENCE_EMPTY_MESSAGE)

    def test_single_category_is_one_hundred_percent(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "gezi"),
            make_activity(2, PAST_DATE, PAST_TIME, "gezi"),
        ]
        result = build_experience_presentation(created, [])
        self.assertEqual(result["categories"][0]["percent"], 100)
        self.assertEqual(sum(item["percent"] for item in result["categories"]), 100)
        path = result["categories"][0]["arc_d"]
        self.assertIn(" A 40 40 0 1 1 ", path)
        self.assertGreater(wheel_sweep_degrees(1), 180)

    def test_displayed_percents_sum_to_one_hundred(self):
        counts = {"kahve": 1, "spor": 1, "kitap": 1}
        percents = allocate_display_percents(counts)
        self.assertEqual(sum(percents.values()), 100)
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "kahve"),
            make_activity(2, PAST_DATE, PAST_TIME, "yeme"),
            make_activity(3, PAST_DATE, PAST_TIME, "spor"),
        ]
        result = build_experience_presentation(created, [])
        self.assertEqual(sum(item["percent"] for item in result["categories"]), 100)
        self.assertTrue(all(item["percent"] > 0 for item in result["categories"]))

    def test_foreign_plans_are_ignored_unless_in_source_lists(self):
        own = make_activity(1, PAST_DATE, PAST_TIME, "kahve")
        foreign = make_activity(99, PAST_DATE, PAST_TIME, "hobi")
        result = build_experience_presentation([own], [])
        keys = [item["key"] for item in result["categories"]]
        self.assertEqual(result["total"], 1)
        self.assertNotIn("hobi", keys)
        self.assertIs(foreign.id, 99)

    def test_small_share_and_many_categories_still_produce_arcs(self):
        created = [make_activity(1, PAST_DATE, PAST_TIME, "kahve")]
        joined = [
            make_activity(index, PAST_DATE, PAST_TIME, key)
            for index, key in enumerate(
                ("yeme", "spor", "sanat", "kitap", "doga", "gezi", "hobi", "diger"),
                start=2,
            )
        ]
        result = build_experience_presentation(created, joined)
        self.assertEqual(result["total"], 9)
        self.assertEqual(sum(item["percent"] for item in result["categories"]), 100)
        self.assertEqual(len(result["categories"]), 9)
        sweep = wheel_sweep_degrees(9)
        self.assertGreaterEqual(sweep, 12)
        for item in result["categories"]:
            self.assertTrue(item["arc_d"].startswith("M "))
            self.assertIn(" A 40 40 0 0 1 ", item["arc_d"])
            self.assertGreater(item["percent"], 0)

    def test_today_event_uses_actual_time(self):
        from datetime import timedelta

        from app import TURKEY_TZ, datetime as app_datetime

        now = app_datetime.now(TURKEY_TZ)
        past_at = now - timedelta(minutes=5)
        future_at = now + timedelta(minutes=5)
        past_today = make_activity(
            21,
            past_at.strftime("%Y-%m-%d"),
            past_at.strftime("%H:%M"),
            "kahve",
        )
        future_today = make_activity(
            22,
            future_at.strftime("%Y-%m-%d"),
            future_at.strftime("%H:%M"),
            "spor",
        )
        result = build_experience_presentation([past_today, future_today], [])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["categories"][0]["key"], "kahve")

    def test_activity_model_has_no_cancel_or_draft_state(self):
        from app import Activity

        column_names = {column.name for column in Activity.__table__.columns}
        self.assertNotIn("status", column_names)
        self.assertNotIn("is_active", column_names)
        self.assertNotIn("is_cancelled", column_names)
        self.assertNotIn("cancelled", column_names)
        self.assertNotIn("draft", column_names)
        self.assertNotIn("is_draft", column_names)


class IsolatedExperienceDbTests(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from werkzeug.security import generate_password_hash

        from app import (
            Activity,
            ActivityParticipant,
            Friendship,
            User,
            app,
            db,
        )

        self.app = app
        self.db = db
        self.Activity = Activity
        self.ActivityParticipant = ActivityParticipant
        self.Friendship = Friendship
        self.original_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        fd, self.temp_db_path = tempfile.mkstemp(suffix="-experience-test.db")
        os.close(fd)
        self._rebind("sqlite:///" + self.temp_db_path)
        with app.app_context():
            current_url = str(db.engine.url)
            if self.temp_db_path not in current_url:
                self._rebind(self.original_uri)
                raise RuntimeError(
                    f"Test DB switch failed; still on {current_url}"
                )
            db.create_all()
            self.owner = User(
                full_name="Sude Test",
                email="sude-exp@example.com",
                password_hash=generate_password_hash("secret"),
            )
            self.other = User(
                full_name="Mert Test",
                email="mert-exp@example.com",
                password_hash=generate_password_hash("secret"),
            )
            db.session.add_all([self.owner, self.other])
            db.session.commit()
            self.owner_id = self.owner.id
            self.other_id = self.other.id
            self.owner_name = self.owner.full_name
            self.other_name = self.other.full_name

    def tearDown(self):
        import os

        from app import app, db

        with app.app_context():
            db.session.remove()
        self._rebind(self.original_uri)
        try:
            os.unlink(self.temp_db_path)
        except OSError:
            pass

    def _rebind(self, uri):
        from app import app, db

        app.config["SQLALCHEMY_DATABASE_URI"] = uri
        with app.app_context():
            db.session.remove()
            engines = db._app_engines[app]
            for engine in list(engines.values()):
                engine.dispose()
            engines.clear()
            options = {"url": uri}
            db._apply_driver_defaults(options, app)
            engines[None] = db._make_engine(None, options, app)

    def _user(self, user_id):
        from app import User

        return self.db.session.get(User, user_id)

    def _add_activity(
        self,
        creator_id,
        date,
        time,
        category="kahve",
        title="Plan",
        visibility="public",
    ):
        activity = self.Activity(
            title=title,
            description="Test plan",
            date=date,
            time=time,
            location="Kadıköy",
            visibility=visibility,
            category=category,
            creator_id=creator_id,
        )
        self.db.session.add(activity)
        self.db.session.commit()
        return activity

    def _add_participation(self, user_id, activity, status):
        row = self.ActivityParticipant(
            user_id=user_id,
            activity_id=activity.id,
            status=status,
        )
        self.db.session.add(row)
        self.db.session.commit()
        return row

    def test_profile_route_empty_and_filled_render(self):
        from app import EXPERIENCE_EMPTY_MESSAGE, get_profile_context

        with self.app.app_context():
            with self.app.test_request_context():
                empty_context = get_profile_context(self._user(self.owner_id))
            self.assertEqual(empty_context["experience"]["total"], 0)
            self.assertTrue(empty_context["experience"]["is_empty"])

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = self.owner_id
            session["user_name"] = self.owner_name
        empty_response = client.get("/profile")
        self.assertEqual(empty_response.status_code, 200)
        empty_html = empty_response.get_data(as_text=True)
        self.assertIn("activity-wheel--empty", empty_html)
        self.assertIn(EXPERIENCE_EMPTY_MESSAGE, empty_html)
        self.assertNotIn('class="experience-details-toggle"', empty_html)
        self.assertNotIn('aria-controls="experience-details"', empty_html)
        self.assertNotIn('id="experience-details"', empty_html)
        self.assertNotIn('class="experience-details-chevron"', empty_html)
        self.assertNotIn("Sosyal deneyim özeti (prototip)", empty_html)

        with self.app.app_context():
            self._add_activity(self.owner_id, PAST_DATE, PAST_TIME, "kahve", "Geçmiş kahve")
            with self.app.test_request_context():
                filled_context = get_profile_context(self._user(self.owner_id))
            self.assertEqual(filled_context["experience"]["total"], 1)
            self.assertEqual(
                filled_context["experience"]["categories"][0]["key"], "kahve"
            )

        filled_html = client.get("/profile").get_data(as_text=True)
        self.assertIn("Kahve", filled_html)
        self.assertIn("experience-legend", filled_html)
        self.assertIn("%100", filled_html)
        self.assertIn("1 tamamlanmış deneyim", filled_html)
        self.assertIn("1 deneyim", filled_html)
        self.assertIn("Deneyim özeti", filled_html)
        self.assertIn('type="button"', filled_html)
        self.assertIn('class="experience-details-toggle"', filled_html)
        self.assertIn('class="experience-details-icon"', filled_html)
        self.assertIn('aria-expanded="false"', filled_html)
        self.assertIn('aria-controls="experience-details"', filled_html)
        self.assertIn('id="experience-details"', filled_html)
        self.assertIn('class="experience-details-chevron"', filled_html)
        self.assertRegex(filled_html, r'id="experience-details"[^>]*\bhidden\b')
        self.assertIn("experience-legend-item is-kahve", filled_html)
        self.assertIn("experience-legend-bar", filled_html)
        self.assertIn("experience-legend-swatch is-kahve", filled_html)
        self.assertIn("experience-legend-name", filled_html)
        self.assertIn("experience-legend-meta", filled_html)
        self.assertIn("experience-legend-percent", filled_html)
        self.assertRegex(
            filled_html,
            r'class="experience-legend-item is-kahve"[^>]*style="--experience-percent:\s*100%;?"',
        )
        self.assertNotIn("activity-wheel--empty", filled_html)

    def test_owner_and_other_user_experiences_are_isolated(self):
        from app import get_profile_context

        with self.app.app_context():
            self._add_activity(
                self.owner_id, PAST_DATE, PAST_TIME, "kitap", "Sahip planı"
            )
            other_plan = self._add_activity(
                self.other_id, PAST_DATE, PAST_TIME, "spor", "Başka plan"
            )
            self._add_participation(self.owner_id, other_plan, "joined")
            future_plan = self._add_activity(
                self.other_id, FUTURE_DATE, FUTURE_TIME, "gezi", "Gelecek"
            )
            self._add_participation(self.owner_id, future_plan, "joined")
            maybe_plan = self._add_activity(
                self.other_id, PAST_DATE, PAST_TIME, "doga", "Belki plan"
            )
            self._add_participation(self.owner_id, maybe_plan, "maybe")

            with self.app.test_request_context():
                owner_context = get_profile_context(self._user(self.owner_id))
                other_context = get_profile_context(
                    self._user(self.other_id), viewer=self._user(self.owner_id)
                )

            owner_keys = [
                item["key"] for item in owner_context["experience"]["categories"]
            ]
            other_keys = [
                item["key"] for item in other_context["experience"]["categories"]
            ]
            self.assertEqual(owner_context["experience"]["total"], 2)
            self.assertCountEqual(owner_keys, ["kitap", "spor"])
            self.assertEqual(other_context["experience"]["total"], 2)
            self.assertCountEqual(other_keys, ["spor", "doga"])
            self.assertNotEqual(
                owner_context["profile_user"]["handle"],
                other_context["profile_user"]["handle"],
            )

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = self.owner_id
            session["user_name"] = self.owner_name
        own_html = client.get("/profile").get_data(as_text=True)
        other_page = client.get(f"/users/{self.other_id}")
        self.assertEqual(other_page.status_code, 200)
        other_html = other_page.get_data(as_text=True)
        self.assertIn("activity-wheel", own_html)
        self.assertIn("Kitap", own_html)
        self.assertIn("experience-legend-item is-kitap", own_html)
        self.assertIn("experience-legend-item is-spor", own_html)
        self.assertRegex(own_html, r'--experience-percent:\s*\d+%;?')
        self.assertIn("activity-wheel", other_html)
        self.assertIn("experience-legend", other_html)
        self.assertIn("experience-legend-item is-spor", other_html)
        self.assertIn("experience-legend-item is-doga", other_html)
        self.assertIn("experience-legend-bar", other_html)
        self.assertIn("experience-legend-swatch is-spor", other_html)
        self.assertIn("experience-legend-swatch is-doga", other_html)
        self.assertIn("experience-legend-name", other_html)
        self.assertIn("experience-legend-meta", other_html)
        self.assertIn("experience-legend-percent", other_html)
        self.assertRegex(
            other_html,
            r'class="experience-legend-item is-spor"[^>]*style="--experience-percent:\s*50%;?"',
        )
        self.assertRegex(
            other_html,
            r'class="experience-legend-item is-doga"[^>]*style="--experience-percent:\s*50%;?"',
        )
        self.assertNotIn("experience-legend-item is-kitap", other_html)
        self.assertIn("Sosyal Deneyim Çemberi", other_html)
        self.assertIn("Deneyim özeti", other_html)
        self.assertIn('class="activity-wheel-arc is-spor', other_html)
        self.assertIn('class="activity-wheel-arc is-doga', other_html)
        self.assertNotIn('class="activity-wheel-arc is-kitap', other_html)
        self.assertIn('aria-controls="experience-details"', other_html)
        self.assertIn('aria-expanded="false"', other_html)
        self.assertRegex(other_html, r'id="experience-details"[^>]*\bhidden\b')
        self.assertIn("mert", other_html.lower())

    def test_other_user_experience_respects_existing_visibility_rules(self):
        with self.app.app_context():
            self._add_activity(
                self.other_id,
                PAST_DATE,
                PAST_TIME,
                "kahve",
                "Herkese açık plan",
            )
            self._add_activity(
                self.other_id,
                PAST_DATE,
                PAST_TIME,
                "kitap",
                "Arkadaş planı",
                visibility="friends",
            )

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = self.owner_id
            session["user_name"] = self.owner_name

        non_friend_html = client.get(f"/users/{self.other_id}").get_data(as_text=True)
        self.assertIn('class="activity-wheel-arc is-kahve', non_friend_html)
        self.assertNotIn('class="activity-wheel-arc is-kitap', non_friend_html)
        self.assertIn("1 tamamlanmış deneyim", non_friend_html)

        with self.app.app_context():
            self.db.session.add(
                self.Friendship(
                    sender_id=self.owner_id,
                    receiver_id=self.other_id,
                    status="accepted",
                )
            )
            self.db.session.commit()

        friend_html = client.get(f"/users/{self.other_id}").get_data(as_text=True)
        self.assertIn('class="activity-wheel-arc is-kahve', friend_html)
        self.assertIn('class="activity-wheel-arc is-kitap', friend_html)
        self.assertIn("2 tamamlanmış deneyim", friend_html)

    def test_unauthenticated_profile_redirects_to_login(self):
        response = self.app.test_client().get("/profile", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))


def extract_legend_html(html):
    match = re.search(
        r'<ul class="experience-legend"[^>]*>.*?</ul>',
        html,
        flags=re.S,
    )
    return match.group(0) if match else ""


class ExperienceWheelTemplateTests(unittest.TestCase):
    def setUp(self):
        from app import app, build_letter_avatar

        self.ctx = app.app_context()
        self.ctx.push()
        self.request_ctx = app.test_request_context()
        self.request_ctx.push()
        self.profile_user = {
            "first_name": "Sude",
            "possessive_first_name": "Sude'nin",
            "handle": "@sude",
            "bio": "Henüz biyografi eklenmedi.",
            "avatar": build_letter_avatar("Sude"),
        }
        self.stats = {
            "created_count": 0,
            "joined_count": 0,
            "friends_count": 0,
        }
        self.empty_sections = {"upcoming": [], "past": []}

    def tearDown(self):
        self.request_ctx.pop()
        self.ctx.pop()

    def _render(self, experience, template_name="profile.html"):
        from flask import render_template

        kwargs = {
            "profile_user": self.profile_user,
            "stats": self.stats,
            "created": self.empty_sections,
            "joined": self.empty_sections,
            "experience": experience,
        }
        if template_name == "user_profile.html":
            kwargs.update(
                viewed_user=SimpleNamespace(id=99),
                friendship=None,
                friendship_state="add",
                back_url="/",
                from_activity="",
                detail_from="",
                detail_q="",
                detail_filter="all",
                detail_user_id="",
            )
        return render_template(template_name, **kwargs)

    def _assert_mini_bar_rows(self, html, categories):
        from html import unescape

        text = unescape(html)
        self.assertIn("experience-legend", html)
        self.assertIn("experience-legend-bar", html)
        self.assertIn("experience-legend-name", html)
        self.assertIn("experience-legend-meta", html)
        self.assertIn("experience-legend-percent", html)
        for item in categories:
            self.assertIn(f'experience-legend-item is-{item["key"]}', html)
            self.assertIn(f"experience-legend-swatch is-{item['key']}", html)
            self.assertIn(item["label"], text)
            self.assertIn(f"%{item['percent']}", html)
            self.assertRegex(
                html,
                rf'class="experience-legend-item is-{item["key"]}"[^>]*'
                rf'style="--experience-percent:\s*{item["percent"]}%;?"',
            )

    def test_empty_template_shows_empty_message(self):
        html = self._render(build_experience_presentation([], []))
        self.assertIn("activity-wheel--empty", html)
        self.assertIn("Sosyal Deneyim Çemberi", html)
        self.assertIn(EXPERIENCE_EMPTY_MESSAGE, html)
        self.assertNotIn("experience-legend", html)
        self.assertNotIn("experience-total", html)
        self.assertNotIn("0 tamamlanmış deneyim", html)
        self.assertNotIn('class="experience-details-toggle"', html)
        self.assertNotIn('aria-controls="experience-details"', html)
        self.assertNotIn('id="experience-details"', html)
        self.assertNotIn('class="experience-details-chevron"', html)
        self.assertNotIn("Sosyal deneyim özeti (prototip)", html)

    def test_filled_template_shows_legend_and_arcs(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "kahve"),
            make_activity(2, PAST_DATE, PAST_TIME, "spor"),
        ]
        html = self._render(build_experience_presentation(created, []))
        self.assertNotIn("activity-wheel--empty", html)
        self.assertIn("Sosyal Deneyim Çemberi", html)
        self.assertIn("2 tamamlanmış deneyim", html)
        self.assertIn("experience-legend", html)
        self.assertIn("Kahve", html)
        self.assertIn("Spor", html)
        self.assertIn("1 deneyim", html)
        self.assertIn("%50", html)
        self.assertIn("tamamlanmış sosyal deneyim", html)
        self.assertIn("activity-wheel-arc is-kahve", html)
        self.assertIn("activity-wheel-arc is-spor", html)
        self.assertIn("Deneyim özeti", html)
        self.assertIn('class="experience-details-toggle"', html)
        self.assertIn('type="button"', html)
        self.assertIn('data-experience-toggle-label', html)
        self.assertIn('class="experience-details-icon"', html)
        self.assertIn('class="experience-details-chevron"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn('aria-controls="experience-details"', html)
        self.assertRegex(
            html,
            r'<button[^>]*type="button"[^>]*aria-expanded="false"[^>]*aria-controls="experience-details"',
        )
        self.assertRegex(html, r'id="experience-details"[^>]*\bhidden\b')
        self.assertLess(
            html.find("Deneyim özeti"),
            html.find('id="experience-details"'),
        )
        button_html = html[
            html.find('class="experience-details-toggle"'):html.find('id="experience-details"')
        ]
        self.assertIn("experience-details-icon", button_html)
        self.assertIn("experience-details-chevron", button_html)
        self.assertIn("Deneyim özeti", button_html)
        self.assertLess(
            button_html.find("experience-details-icon"),
            button_html.find("Deneyim özeti"),
        )
        self.assertLess(
            button_html.find("Deneyim özeti"),
            button_html.find("experience-details-chevron"),
        )
        details_html = html[
            html.find('id="experience-details"'):html.find('class="plans-title"')
        ]
        self.assertIn("2 tamamlanmış deneyim", details_html)
        self.assertIn("Kahve", details_html)
        self.assertIn("1 deneyim", details_html)
        self.assertIn("%50", details_html)
        self.assertIn("experience-legend-item is-kahve", details_html)
        self.assertIn("experience-legend-item is-spor", details_html)
        self.assertIn("experience-legend-bar", details_html)
        self.assertIn("experience-legend-swatch is-kahve", details_html)
        self.assertIn("experience-legend-swatch is-spor", details_html)
        self.assertIn("experience-legend-name", details_html)
        self.assertIn("experience-legend-meta", details_html)
        self.assertIn("experience-legend-percent", details_html)
        self.assertRegex(
            details_html,
            r'class="experience-legend-item is-kahve"[^>]*style="--experience-percent:\s*50%;?"',
        )
        self.assertRegex(
            details_html,
            r'class="experience-legend-item is-spor"[^>]*style="--experience-percent:\s*50%;?"',
        )
        self.assertNotIn("Deneyim özeti", details_html)

        experience = build_experience_presentation(created, [])
        self._assert_mini_bar_rows(html, experience["categories"])

    def test_filled_template_uses_plural_category_count(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "kahve"),
            make_activity(2, PAST_DATE, PAST_TIME, "kahve"),
        ]
        html = self._render(build_experience_presentation(created, []))
        self.assertIn("2 tamamlanmış deneyim", html)
        self.assertIn("2 deneyim", html)
        self.assertIn("%100", html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("Deneyim özeti", html)
        self.assertIn('class="experience-details-icon"', html)
        self.assertIn('class="experience-details-chevron"', html)

    def test_legend_swatches_reuse_wheel_category_colors(self):
        from html import unescape
        from pathlib import Path

        from app import ACTIVITY_CATEGORY_LABELS

        created = [
            make_activity(index, PAST_DATE, PAST_TIME, key)
            for index, key in enumerate(ACTIVITY_CATEGORY_LABELS, start=1)
        ]
        html = self._render(build_experience_presentation(created, []))
        details_html = html[
            html.find('id="experience-details"'):html.find('class="plans-title"')
        ]
        details_text = unescape(details_html)
        self.assertIn("Yeme & İçme", details_text)
        experience = build_experience_presentation(created, [])
        self._assert_mini_bar_rows(details_html, experience["categories"])
        for key, label in ACTIVITY_CATEGORY_LABELS.items():
            self.assertIn(f"experience-legend-item is-{key}", details_html)
            self.assertIn(f"experience-legend-swatch is-{key}", details_html)
            self.assertIn(label, details_text)

        css_path = Path(__file__).resolve().parents[1] / "static" / "css" / "activity_wheel.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn(".activity-wheel,\n.experience-details", css)
        for key in ACTIVITY_CATEGORY_LABELS:
            self.assertIn(f"--aw-{key}:", css)
            self.assertRegex(
                css,
                rf"\.experience-legend-swatch\.is-{key}\s*\{{[^}}]*var\(--aw-{key}\)",
            )
            self.assertRegex(
                css,
                rf"\.experience-legend-item\.is-{key}\s*\{{[^}}]*var\(--aw-{key}\)",
            )

        bar_match = re.search(r"\.experience-legend-bar\s*\{([^}]+)\}", css)
        self.assertIsNotNone(bar_match)
        bar_css = bar_match.group(1)
        self.assertIn("width: var(--experience-percent)", bar_css)
        self.assertNotIn("min-width", bar_css)
        self.assertRegex(bar_css, r"opacity:\s*0\.0[5-9]")
        self.assertNotRegex(css, r"--experience-percent\)\s*\*\s*")
        self.assertRegex(
            css,
            r"\.experience-legend\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)",
        )
        self.assertIn(".experience-legend-item:nth-child(5)", css)
        self.assertIn("@container experience-panel (min-width: 720px)", css)
        panel_match = re.search(
            r"\.experience-details \{\n    width: 100%;[^}]+\}",
            css,
        )
        self.assertIsNotNone(panel_match)
        panel_css = panel_match.group(0)
        self.assertNotIn("max-height", panel_css)
        self.assertNotRegex(panel_css, r"overflow(-y)?:\s*(auto|scroll)")
        self.assertIn("flex-shrink: 0", css)
        self.assertRegex(
            css,
            r"\.experience-legend-meta\s*\{[^}]*white-space:\s*nowrap",
        )

    def test_own_and_visited_profiles_share_mini_bar_markup(self):
        created = [
            make_activity(1, PAST_DATE, PAST_TIME, "kahve"),
            make_activity(2, PAST_DATE, PAST_TIME, "yeme"),
            make_activity(3, PAST_DATE, PAST_TIME, "spor"),
        ]
        experience = build_experience_presentation(created, [])
        own_html = self._render(experience, "profile.html")
        other_html = self._render(experience, "user_profile.html")

        self._assert_mini_bar_rows(own_html, experience["categories"])
        self._assert_mini_bar_rows(other_html, experience["categories"])
        self.assertEqual(extract_legend_html(own_html), extract_legend_html(other_html))
        self.assertRegex(own_html, r'id="experience-details"[^>]*\bhidden\b')
        self.assertRegex(other_html, r'id="experience-details"[^>]*\bhidden\b')
        self.assertIn('aria-expanded="false"', own_html)
        self.assertIn('aria-expanded="false"', other_html)
        self.assertIn('aria-controls="experience-details"', own_html)
        self.assertIn('aria-controls="experience-details"', other_html)

        empty_own = self._render(build_experience_presentation([], []), "profile.html")
        empty_other = self._render(
            build_experience_presentation([], []), "user_profile.html"
        )
        self.assertNotIn('class="experience-details-toggle"', empty_own)
        self.assertNotIn('id="experience-details"', empty_own)
        self.assertNotIn('class="experience-details-toggle"', empty_other)
        self.assertNotIn('id="experience-details"', empty_other)


if __name__ == "__main__":
    unittest.main()
