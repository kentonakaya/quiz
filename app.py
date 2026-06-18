import os
from flask import Flask
from extensions import db, socketio
from controller.controllers import quiz_bp


def create_app() -> Flask:
    # Set instance path explicitly to the directory where this file resides + /instance
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)

    app = Flask(__name__, instance_path=instance_path)
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"sqlite:///{os.path.join(instance_path, 'quiz_event.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = "quiz-bet-event-secret-2026"

    db.init_app(app)
    socketio.init_app(app)
    app.register_blueprint(quiz_bp)

    @app.context_processor
    def inject_team_points():
        from flask import session
        from repository import repositories

        team_points = 0
        if "team_id" in session:
            team = repositories.get_team_by_id(session["team_id"])
            if team:
                team_points = team.points
        return dict(team_points=team_points)

    with app.app_context():
        db.create_all()
        seed_event_data()

    return app


def seed_event_data():
    from model.models import Team, QuizQuestion, BetEvent, BingoTheme, BetOption

    print("Syncing quiz and betting database...")

    # 1. Sync Teams 1 to 20
    for i in range(1, 21):
        team_name = f"チーム {i}"
        team = Team.query.filter_by(team_name=team_name).first()
        if not team:
            db.session.add(Team(team_name=team_name, points=500))

    # 2. Sync 9 Bingo Themes (3x3 grid)
    bingo_themes_data = [
        "血液型が同じ人がいる",
        "出身地方が同じ人がいる",
        "趣味が似ている人がいる",
        "好きな食べ物が同じ",
        "休日の過ごし方が同じ",
        "持っている資格が同じ",
        "学生時代の部活が同じ",
        "最近買った高いものが同じ",
        "実は苦手なものが同じ",
    ]
    for i, text in enumerate(bingo_themes_data, 1):
        theme = BingoTheme.query.filter_by(position=i).first()
        if theme:
            theme.theme_text = text
        else:
            db.session.add(BingoTheme(position=i, theme_text=text))

    # 3. Sync Quiz Questions
    quiz_data = [
        {
            "num": 1,
            "text": "全社員が、Excelを使いながら最も「自社への愛」を感じる瞬間は、当然「Shiftキー」を押すときですよね。 では、Excelで「Shiftキーを押しながら、F11キー」を叩くと、一体何が起きるでしょう？",
            "a": "無駄な工数の徹底的な削減",
            "b": "新たなフィールドの創出",
            "c": "自身の限界を超えるキャリアアップ",
            "d": "不具合の出ない完璧な品質保証",
            "correct": "B",
        },
        {
            "num": 2,
            "text": "パワポ（一期一会？）",
            "a": "A",
            "b": "B",
            "c": "C",
            "d": "D",
            "correct": "A",
        },
        {
            "num": 3,
            "text": "テスト設計（聖徳太子クイズ？）",
            "a": "A",
            "b": "B",
            "c": "C",
            "d": "D",
            "correct": "B",
        },
        {
            "num": 4,
            "text": "生成AI 1(顔合成)",
            "a": "A",
            "b": "B",
            "c": "C",
            "d": "D",
            "correct": "A",
        },
        {
            "num": 5,
            "text": "生成AI 2（まんぷくんシルエット）",
            "a": "A",
            "b": "B",
            "c": "C",
            "d": "D",
            "correct": "B",
        },
    ]

    current_nums = [q_item["num"] for q_item in quiz_data]
    QuizQuestion.query.filter(~QuizQuestion.question_num.in_(current_nums)).delete(
        synchronize_session=False
    )

    for q_item in quiz_data:
        q = QuizQuestion.query.filter_by(question_num=q_item["num"]).first()
        if q:
            q.question_text = q_item["text"]
            q.choice_a = q_item["a"]
            q.choice_b = q_item["b"]
            q.choice_c = q_item["c"]
            q.choice_d = q_item["d"]
            q.correct_choice = q_item["correct"]
        else:
            db.session.add(
                QuizQuestion(
                    question_num=q_item["num"],
                    question_text=q_item["text"],
                    choice_a=q_item["a"],
                    choice_b=q_item["b"],
                    choice_c=q_item["c"],
                    choice_d=q_item["d"],
                    correct_choice=q_item["correct"],
                )
            )

    # 4. Sync Bet Events
    events_data = [
        {
            "name": "【格付け①】ハイチュウの味を何人当てられるか？",
            "options": [
                ("0〜1問 or 絶対アカン", 0.0),
                ("2問正解", 1.0),
                ("3問正解", 2.0),
                ("4問すべて正解", 3.5),
            ],
        },
        {
            "name": "【格付け②】箱の中身はなんだろな？（あべりこ戦）",
            "options": [
                ("全滅", 1.5),
                ("Aのみ正解", 2.0),
                ("Bのみ正解", 2.5),
                ("Cのみ正解", 3.5),
                ("A & B 正解", 4.0),
                ("A & C 正解", 5.0),
                ("B & C 正解", 6.5),
                ("3つ全て正解", 10.0),
            ],
        },
        {
            "name": "【格付け③】箱の中身はなんだろな？（わっきー戦）",
            "options": [
                ("全滅", 1.5),
                ("Aのみ正解", 2.0),
                ("Bのみ正解", 2.5),
                ("Cのみ正解", 3.5),
                ("A & B 正解", 4.0),
                ("A & C 正解", 5.0),
                ("B & C 正解", 6.5),
                ("3つ全て正解", 10.0),
            ],
        },
    ]

    for e_item in events_data:
        event = BetEvent.query.filter_by(event_name=e_item["name"]).first()
        if not event:
            event = BetEvent(event_name=e_item["name"], multiplier=0.0) # multiplier column is deprecated
            db.session.add(event)
            db.session.flush() # Get event_id
        
        # Sync Options
        existing_options = {opt.option_text: opt for opt in BetOption.query.filter_by(event_id=event.event_id).all()}
        for opt_text, mult in e_item["options"]:
            if opt_text in existing_options:
                existing_options[opt_text].multiplier = mult
            else:
                db.session.add(BetOption(event_id=event.event_id, option_text=opt_text, multiplier=mult))

    db.session.commit()
    print("Sync completed successfully.")


app = create_app()

if __name__ == "__main__":
    socketio.run(
        app, debug=True, port=8080
    )  # Using port 8080 to not conflict with the seat app
