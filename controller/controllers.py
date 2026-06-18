from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from functools import wraps
from usecase import usecases
from repository import repositories
from extensions import db, socketio

quiz_bp = Blueprint("quiz", __name__)


def team_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "team_id" not in session and not session.get("is_admin"):
            flash("チームを選択するか、管理者としてログインしてください。", "warning")
            return redirect(url_for("quiz.login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            flash("管理者権限が必要です。", "danger")
            return redirect(url_for("quiz.login"))
        return f(*args, **kwargs)

    return decorated_function


# Route: Index Redirect
@quiz_bp.route("/", methods=["GET"])
def index():
    if session.get("is_admin"):
        return redirect(url_for("quiz.admin"))
    if "team_id" in session:
        return redirect(url_for("quiz.bingo"))
    return redirect(url_for("quiz.login"))


# Route: Login / Team Selection
@quiz_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role")
        if role == "admin":
            session.clear()
            session["is_admin"] = True
            session["name"] = "管理者"
            flash("管理者としてログインしました。", "success")
            return redirect(url_for("quiz.admin"))
        else:
            team_id = request.form.get("team_id", type=int)
            team = repositories.get_team_by_id(team_id)
            if team:
                session.clear()
                session["team_id"] = team.team_id
                session["team_name"] = team.team_name
                flash(f"{team.team_name}として参加しました！", "success")
                return redirect(url_for("quiz.bingo"))

    teams = repositories.get_all_teams()
    return render_template("login.html", teams=teams)


# Route: Logout
@quiz_bp.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。", "info")
    return redirect(url_for("quiz.login"))


# Route: Bingo (Common Points Grid)
@quiz_bp.route("/bingo", methods=["GET", "POST"])
@team_required
def bingo():
    team_id = session.get("team_id")
    if request.method == "POST":
        if not team_id:
            flash("管理者アカウントでは投稿できません。", "warning")
            return redirect(url_for("quiz.bingo"))

        position = request.form.get("position", type=int)
        content = request.form.get("content")
        success, message = usecases.submit_bingo_answer(team_id, position, content)
        if success:
            socketio.emit(
                "bingo_submitted",
                {"team_id": team_id, "position": position},
                namespace="/",
            )
            flash(message, "success")
        else:
            flash(message, "danger")
        return redirect(url_for("quiz.bingo"))

    themes = repositories.get_all_bingo_themes()
    squares = []
    if team_id:
        squares = repositories.get_bingo_squares_by_team(team_id)

    # Map squares by position for easy lookup in template
    square_map = {s.position: s for s in squares}

    return render_template("bingo.html", themes=themes, square_map=square_map)


# Route: Live 4-Choice Quiz Answering
@quiz_bp.route("/quiz", methods=["GET", "POST"])
@team_required
def quiz_view():
    team_id = session.get("team_id")

    if request.method == "POST":
        if not team_id:
            flash("管理者アカウントでは回答を送信できません。", "warning")
            return redirect(url_for("quiz.quiz_view"))

        quiz_id = request.form.get("quiz_id", type=int)
        choice = request.form.get("choice")

        success, message = usecases.submit_quiz_answer(quiz_id, team_id, choice)
        if success:
            socketio.emit(
                "quiz_submitted",
                {"team_id": team_id, "quiz_id": quiz_id},
                namespace="/",
            )
            flash(message, "success")
        else:
            flash(message, "danger")
        return redirect(url_for("quiz.quiz_view"))

    # GET: Fetch active question
    active_q = repositories.get_active_question()
    submitted = None

    if active_q and team_id:
        submitted = repositories.get_submission_by_team_and_quiz(
            active_q.quiz_id, team_id
        )

    # Fetch last revealed question for summary
    last_revealed = repositories.get_last_revealed_question()
    last_sub = None
    if last_revealed and team_id:
        last_sub = repositories.get_submission_by_team_and_quiz(
            last_revealed.quiz_id, team_id
        )

    return render_template(
        "quiz.html",
        question=active_q,
        submitted=submitted,
        last_revealed=last_revealed,
        last_sub=last_sub,
    )


# Route: Betting Sub-event
@quiz_bp.route("/bet", methods=["GET", "POST"])
@team_required
def bet_view():
    team_id = session.get("team_id")

    if request.method == "POST":
        if not team_id:
            flash("管理者アカウントではベットできません。", "warning")
            return redirect(url_for("quiz.bet_view"))

        event_id = request.form.get("event_id", type=int)
        bet_points = request.form.get("bet_points", type=int)
        prediction = request.form.get("prediction")
        multiplier = request.form.get("multiplier", type=float, default=2.0)

        success, message = usecases.place_bet(
            event_id, team_id, bet_points, prediction, multiplier
        )
        if success:
            socketio.emit(
                "bet_submitted",
                {"team_id": team_id, "event_id": event_id},
                namespace="/",
            )
            flash(message, "success")
        else:
            flash(message, "danger")
        return redirect(url_for("quiz.bet_view"))

    # GET: Load betting interface
    active_event = repositories.get_active_bet_event()
    submitted_bet = None
    options = []

    if active_event:
        options = repositories.get_options_for_event(active_event.event_id)
        if team_id:
            submitted_bet = repositories.get_bet_by_event_and_team(
                active_event.event_id, team_id
            )

    return render_template(
        "bet.html",
        event=active_event,
        submitted_bet=submitted_bet,
        options=options,
    )


# Route: Leaderboard / Rankings
@quiz_bp.route("/ranking")
def ranking():
    teams = repositories.get_all_teams()
    return render_template("ranking.html", teams=teams)


# Route: Administrator Dashboard
@quiz_bp.route("/admin", methods=["GET"])
@admin_required
def admin():
    questions = repositories.get_all_questions()
    events = repositories.get_all_events()
    teams = repositories.get_all_teams()
    pending_squares = repositories.get_pending_bingo_squares()
    themes = repositories.get_all_bingo_themes()

    # Check if there's any active bet event to show bets table
    active_event = repositories.get_active_bet_event()
    bets = []
    if active_event:
        bets = repositories.get_bets_for_event(active_event.event_id)

    # Create a map of options for all events to support settlement buttons
    options_map = {}
    for e in events:
        options_map[e.event_id] = repositories.get_options_for_event(e.event_id)

    team_map = {t.team_id: t.team_name for t in teams}

    return render_template(
        "admin.html",
        questions=questions,
        events=events,
        teams=teams,
        pending_squares=pending_squares,
        themes=themes,
        active_event=active_event,
        bets=bets,
        options_map=options_map,
        team_map=team_map,
    )


# Admin Action: Approve/Reject Bingo Square
@quiz_bp.route("/admin/bingo/<int:square_id>/approve", methods=["POST"])
@admin_required
def admin_approve_bingo(square_id: int):
    status = request.form.get("status")  # 'approved' or 'rejected'
    success, message = usecases.approve_bingo_square(square_id, status)
    if success:
        socketio.emit(
            "bingo_update", {"square_id": square_id, "status": status}, namespace="/"
        )
        flash(message, "success")
    else:
        flash(message, "danger")
    return redirect(url_for("quiz.admin"))


# Admin Action: Start/Activate Quiz
@quiz_bp.route("/admin/quiz/<int:quiz_id>/activate", methods=["POST"])
@admin_required
def admin_activate_quiz(quiz_id: int):
    # Hide all other active quizzes first
    active = repositories.get_active_question()
    if active:
        repositories.update_question_status(active.quiz_id, "hidden")

    repositories.update_question_status(quiz_id, "active")
    socketio.emit(
        "quiz_update", {"status": "active", "quiz_id": quiz_id}, namespace="/"
    )
    flash(f"第 {quiz_id} 問の回答受付を開始しました！", "success")
    return redirect(url_for("quiz.admin"))


# Admin Action: Reveal Correct Answer of Quiz
@quiz_bp.route("/admin/quiz/<int:quiz_id>/reveal", methods=["POST"])
@admin_required
def admin_reveal_quiz(quiz_id: int):
    award_points = request.form.get("award_points", default=100, type=int)
    success, message = usecases.reveal_quiz_answer(quiz_id, award_points)
    if success:
        socketio.emit(
            "quiz_update", {"status": "revealed", "quiz_id": quiz_id}, namespace="/"
        )
        flash(message, "success")
    else:
        flash(message, "danger")
    return redirect(url_for("quiz.admin"))


# Admin Action: Set/Activate Bet Event Status
@quiz_bp.route("/admin/event/<int:event_id>/status", methods=["POST"])
@admin_required
def admin_set_event_status(event_id: int):
    status = request.form.get("status")
    # If starting, close others
    if status == "betting":
        active = repositories.get_active_bet_event()
        if active:
            repositories.update_event_status(active.event_id, "waiting")

    repositories.update_event_status(event_id, status)
    socketio.emit(
        "event_update", {"status": status, "event_id": event_id}, namespace="/"
    )
    flash(f"イベントステータスを {status} に変更しました。", "success")
    return redirect(url_for("quiz.admin"))


# Admin Action: Settle Payout for Bet Event
@quiz_bp.route("/admin/event/<int:event_id>/settle", methods=["POST"])
@admin_required
def admin_settle_event(event_id: int):
    winning_prediction = request.form.get("winning_prediction")
    success, message = usecases.settle_bet_event(event_id, winning_prediction)
    if success:
        socketio.emit(
            "event_update", {"status": "settled", "event_id": event_id}, namespace="/"
        )
        flash(message, "success")
    else:
        flash(message, "danger")
    return redirect(url_for("quiz.admin"))


# Admin Action: Reset Game Data / Points
@quiz_bp.route("/admin/reset", methods=["POST"])
@admin_required
def admin_reset():
    try:
        from model.models import QuizSubmission, TeamBet, BingoSquare

        # Reset team scores to 500pt
        for team in repositories.get_all_teams():
            team.points = 500

        # Delete submissions
        QuizSubmission.query.delete()
        # Delete bets
        TeamBet.query.delete()
        # Delete bingo squares
        BingoSquare.query.delete()

        # Reset question statuses to hidden
        for q in repositories.get_all_questions():
            q.status = "hidden"

        # Reset event statuses to waiting
        for e in repositories.get_all_events():
            e.status = "waiting"

        db.session.commit()
        socketio.emit("reset_all", {}, namespace="/")
        flash(
            "すべての企画データをリセットし、各チームの持ち点を 500pt に初期化しました。",
            "success",
        )
    except Exception as e:
        db.session.rollback()
        flash(f"リセットエラー: {str(e)}", "danger")
    return redirect(url_for("quiz.admin"))


@quiz_bp.route("/admin/team/points", methods=["POST"])
@admin_required
def admin_update_points():
    team_id = request.form.get("team_id", type=int)
    points = request.form.get("points", type=int)
    repositories.update_team_points(team_id, points)
    socketio.emit(
        "points_update", {"team_id": team_id, "points": points}, namespace="/"
    )
    flash(f"チームの持ち点を {points}pt に更新しました。", "success")
    return redirect(url_for("quiz.admin"))


@quiz_bp.route("/admin/quiz/<int:quiz_id>/update", methods=["POST"])
@admin_required
def admin_update_quiz(quiz_id):
    q = repositories.get_question_by_id(quiz_id)
    if q:
        q.question_text = request.form.get("question_text")
        q.choice_a = request.form.get("choice_a")
        q.choice_b = request.form.get("choice_b")
        q.choice_c = request.form.get("choice_c")
        q.choice_d = request.form.get("choice_d")
        q.correct_choice = request.form.get("correct_choice")
        db.session.commit()
        flash(f"第 {q.question_num} 問を更新しました。", "success")
    return redirect(url_for("quiz.admin"))


@quiz_bp.route("/admin/bingo/theme", methods=["POST"])
@admin_required
def admin_update_bingo_theme():
    position = request.form.get("position", type=int)
    theme_text = request.form.get("theme_text")
    repositories.update_bingo_theme(position, theme_text)
    flash(f"ビンゴ第 {position} マスのお題を更新しました。", "success")
    return redirect(url_for("quiz.admin"))


@quiz_bp.route("/admin/event/<int:event_id>/update", methods=["POST"])
@admin_required
def admin_update_event(event_id):
    event = repositories.get_event_by_id(event_id)
    if event:
        event.event_name = request.form.get("event_name")
        event.multiplier = request.form.get("multiplier", type=float)
        db.session.commit()
        flash(f"イベント「{event.event_name}」を更新しました。", "success")
    return redirect(url_for("quiz.admin"))
