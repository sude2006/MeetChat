import unittest


class AuthPageTests(unittest.TestCase):
    def setUp(self):
        import os
        import tempfile

        from werkzeug.security import generate_password_hash

        from app import User, app, db

        self.app = app
        self.db = db
        self.User = User
        self.original_uri = app.config["SQLALCHEMY_DATABASE_URI"]
        fd, self.temp_db_path = tempfile.mkstemp(suffix="-auth-test.db")
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
            self.user = User(
                full_name="Sude Auth",
                email="sude-auth@example.com",
                password_hash=generate_password_hash("secret123"),
            )
            db.session.add(self.user)
            db.session.commit()
            self.user_id = self.user.id

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

    def test_login_get_returns_200_with_approved_design(self):
        response = self.app.test_client().get("/login")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("VESİLE", html)
        self.assertIn("Giriş Yap", html)
        self.assertIn("Hesabın yok mu?", html)
        self.assertIn("Kayıt Ol", html)
        self.assertIn('href="/register"', html)
        self.assertIn("Şifremi Unuttum", html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('autocomplete="email"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn('method="post"', html)
        self.assertIn('action="/login"', html)
        self.assertIn('type="button"', html)
        self.assertIn('class="toggle-password"', html)
        self.assertIn('aria-label="Şifreyi göster"', html)
        self.assertIn('id="toggle-password"', html)
        self.assertNotIn("MeetChat", html)
        self.assertNotIn("brand-meet", html)

    def test_register_get_returns_200_with_approved_design(self):
        response = self.app.test_client().get("/register")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("VESİLE", html)
        self.assertIn("Kayıt Ol", html)
        self.assertIn("Zaten hesabın var mı?", html)
        self.assertIn("Giriş Yap", html)
        self.assertIn('href="/login"', html)
        self.assertIn("Şifreniz en az 8 karakter olmalıdır.", html)
        self.assertIn('name="name"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('name="password_confirm"', html)
        self.assertIn('autocomplete="name"', html)
        self.assertIn('autocomplete="email"', html)
        self.assertIn('autocomplete="new-password"', html)
        self.assertIn('method="post"', html)
        self.assertIn('action="/register"', html)
        self.assertEqual(html.count('class="toggle-password"'), 2)
        self.assertIn('data-target="password-input"', html)
        self.assertIn('data-target="password-confirm-input"', html)
        self.assertIn('aria-label="Şifreyi göster"', html)
        self.assertNotIn("MeetChat", html)
        self.assertNotIn("password-hint svg", html)

    def test_valid_user_can_log_in(self):
        client = self.app.test_client()
        response = client.post(
            "/login",
            data={"email": "sude-auth@example.com", "password": "secret123"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers.get("Location", "").endswith("/"))
        with client.session_transaction() as session:
            self.assertEqual(session.get("user_id"), self.user_id)

    def test_invalid_login_shows_existing_error_and_keeps_email(self):
        response = self.app.test_client().post(
            "/login",
            data={"email": "sude-auth@example.com", "password": "wrong-pass"},
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("E-posta veya şifre hatalı.", html)
        self.assertIn('role="alert"', html)
        self.assertIn("sude-auth@example.com", html)

    def test_new_user_can_register_and_is_redirected_to_login(self):
        client = self.app.test_client()
        response = client.post(
            "/register",
            data={
                "name": "Yeni Kullanıcı",
                "email": "yeni@example.com",
                "password": "password1",
                "password_confirm": "password1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers.get("Location", ""))
        with self.app.app_context():
            created = self.User.query.filter_by(email="yeni@example.com").first()
            self.assertIsNotNone(created)
            self.assertEqual(created.full_name, "Yeni Kullanıcı")

    def test_short_password_is_rejected(self):
        response = self.app.test_client().post(
            "/register",
            data={
                "name": "Kısa Şifre",
                "email": "short@example.com",
                "password": "1234567",
                "password_confirm": "1234567",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Şifreniz en az 8 karakter olmalıdır.", html)
        self.assertIn("Kısa Şifre", html)
        self.assertIn("short@example.com", html)
        with self.app.app_context():
            self.assertIsNone(
                self.User.query.filter_by(email="short@example.com").first()
            )

    def test_password_mismatch_is_rejected(self):
        response = self.app.test_client().post(
            "/register",
            data={
                "name": "Uyuşmaz",
                "email": "mismatch@example.com",
                "password": "password1",
                "password_confirm": "password2",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Şifreler uyuşmuyor.", html)
        self.assertIn("Uyuşmaz", html)
        self.assertIn("mismatch@example.com", html)

    def test_existing_email_cannot_register_again(self):
        response = self.app.test_client().post(
            "/register",
            data={
                "name": "Tekrar",
                "email": "sude-auth@example.com",
                "password": "password1",
                "password_confirm": "password1",
            },
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Bu e-posta zaten kayıtlı.", html)

    def test_login_css_keeps_layout_constraints(self):
        from pathlib import Path

        css = (
            Path(__file__).resolve().parents[1] / "static" / "css" / "login.css"
        ).read_text(encoding="utf-8")
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("border-radius: 999px", css)
        self.assertIn("--primary: #17B5BF", css)
        self.assertIn("Fraunces", css)
        self.assertIn("env(safe-area-inset-top", css)
        self.assertIn("pointer-events: none", css)
        self.assertIn(":focus-visible", css)
        self.assertIn(".decor-layer", css)
        shell_css = css.split(".login-shell {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: hidden", shell_css)
        self.assertNotRegex(shell_css, r"overflow-y:\s*(auto|scroll)")


if __name__ == "__main__":
    unittest.main()
