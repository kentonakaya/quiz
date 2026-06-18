from repository import repositories
from extensions import db
from model.models import QuizSubmission, TeamBet, BingoSquare


def calculate_bingo_lines(positions: set[int]) -> int:
    # 3x3 Bingo grid coordinates (1 to 9)
    winning_combinations = [
        {1, 2, 3},
        {4, 5, 6},
        {7, 8, 9},  # Horizontal
        {1, 4, 7},
        {2, 5, 8},
        {3, 6, 9},  # Vertical
        {1, 5, 9},
        {3, 5, 7},  # Diagonal
    ]
    lines = 0
    for combo in winning_combinations:
        if combo.issubset(positions):
            lines += 1
    return lines


def submit_bingo_answer(team_id: int, position: int, content: str) -> tuple[bool, str]:
    if not content or not content.strip():
        return False, "共通点の内容を入力してください。"

    if position < 1 or position > 9:
        return False, "無効なマス位置です。"

    # Insert or update
    repositories.insert_or_update_bingo_square(team_id, position, content)
    return True, f"第 {position} マスの回答を送信しました（承認待ち）。"


def approve_bingo_square(
    square_id: int, status: str, square_reward: int = 10, line_reward: int = 20
) -> tuple[bool, str]:
    """
    Called by admin to approve/reject a team's bingo square.
    If approved, awards points for the square and bonus points for newly completed bingo lines.
    """
    square = repositories.get_bingo_square_by_id(square_id)
    if not square:
        return False, "指定されたマスデータが見つかりません。"

    if square.status == "approved" and status == "approved":
        return False, "この回答は既に承認されています。"

    team = repositories.get_team_by_id(square.team_id)

    if status == "approved":
        # 1. Calculate bingo lines BEFORE approval
        current_squares = repositories.get_bingo_squares_by_team(square.team_id)
        approved_positions_before = {
            s.position for s in current_squares if s.status == "approved"
        }
        lines_before = calculate_bingo_lines(approved_positions_before)

        # 2. Update status of this square to approved
        square.status = "approved"
        db.session.commit()

        # 3. Calculate bingo lines AFTER approval
        approved_positions_after = approved_positions_before | {square.position}
        lines_after = calculate_bingo_lines(approved_positions_after)

        # 4. Award points
        new_lines = lines_after - lines_before
        points_gained = square_reward + (new_lines * line_reward)
        team.points += points_gained
        db.session.commit()

        msg = f"{team.team_name} の第 {square.position} マスを承認しました！(+{points_gained} pt獲得"
        if new_lines > 0:
            msg += f" / ビンゴ {new_lines} ライン達成！"
        msg += ")"
        return True, msg

    elif status == "rejected":
        # Reject: change status to rejected
        square.status = "rejected"
        db.session.commit()
        return (
            True,
            f"{team.team_name} の第 {square.position} マスの回答を却下しました。",
        )

    return False, "無効な操作ステータスです。"


def submit_quiz_answer(
    quiz_id: int, team_id: int, selected_choice: str
) -> tuple[bool, str]:
    q = repositories.get_question_by_id(quiz_id)
    if not q:
        return False, "問題が存在しません。"

    if q.status != "active":
        return False, "この問題は現在、回答を受け付けていません。"

    # Check duplicate submission
    existing = repositories.get_submission_by_team_and_quiz(quiz_id, team_id)
    if existing:
        return False, "この問題には既に回答を送信しています。"

    # For multiple answers, sort the letters (e.g., "BCA" -> "ABC")
    if selected_choice:
        selected_choice = "".join(sorted(selected_choice.upper()))

    repositories.insert_submission(quiz_id, team_id, selected_choice)
    return True, "回答を送信しました！"


def reveal_quiz_answer(quiz_id: int, award_points: int = 100) -> tuple[bool, str]:
    q = repositories.get_question_by_id(quiz_id)
    if not q:
        return False, "問題が見つかりません。"

    if q.status == "revealed":
        return False, "この問題の正解は既に発表されています。"

    # Gather submissions
    submissions = repositories.get_submissions_for_question(quiz_id)

    # Correct choice should also be sorted for comparison
    correct_sorted = "".join(sorted(q.correct_choice.upper()))

    # Check correctness and award points
    for s in submissions:
        if s.selected_choice == correct_sorted:
            s.is_correct = True
            team = repositories.get_team_by_id(s.team_id)
            team.points += award_points

    q.status = "revealed"
    db.session.commit()

    return (
        True,
        f"第{q.question_num}問の正解を発表しました！正当チームに {award_points}pt を付与しました。",
    )


def place_bet(
    event_id: int, team_id: int, bet_points: int, prediction: str, multiplier: float = 2.0
) -> tuple[bool, str]:
    event = repositories.get_event_by_id(event_id)
    if not event:
        return False, "イベントが存在しません。"

    if event.status != "betting":
        return False, "現在、この企画へのベットは受け付けていません。"

    # Check duplicate bet
    existing = repositories.get_bet_by_event_and_team(event_id, team_id)
    if existing:
        return False, "既にこの企画へのベットを完了しています。"

    team = repositories.get_team_by_id(team_id)
    if not team:
        return False, "チームが見つかりません。"

    if bet_points <= 0:
        return False, "1ポイント以上賭ける必要があります。"

    if team.points < bet_points:
        return False, f"保有ポイントが不足しています（現在の持ち点: {team.points}pt）。"

    # Subtract points immediately to lock the bet
    team.points -= bet_points
    repositories.insert_bet(event_id, team_id, bet_points, prediction, multiplier)

    return True, f"{bet_points}pt を賭けて予想「{prediction}」({multiplier}倍) でベット完了しました！"


def settle_bet_event(event_id: int, winning_prediction: str) -> tuple[bool, str]:
    event = repositories.get_event_by_id(event_id)
    if not event:
        return False, "イベントが見つかりません。"

    if event.status == "settled":
        return False, "このイベントは既に清算済みです。"

    bets = repositories.get_bets_for_event(event_id)

    winners_count = 0
    for bet in bets:
        if bet.prediction.strip().upper() == winning_prediction.strip().upper():
            bet.status = "won"
            team = repositories.get_team_by_id(bet.team_id)
            payout = int(bet.bet_points * bet.multiplier)
            team.points += payout
            winners_count += 1
        else:
            bet.status = "lost"

    event.status = "settled"
    db.session.commit()

    return (
        True,
        f"イベントを清算しました。正解は「{winning_prediction}」です。{winners_count} チームが的中しました！",
    )
