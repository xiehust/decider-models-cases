"""Synthetic login-session helper; no persistence or credentials."""


def session_expired(session, now):
    return now >= session['expires_at']
