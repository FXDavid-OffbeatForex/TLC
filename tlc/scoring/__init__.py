"""Local scoring — the public Historian (PRD §2.6).

Down-projects saved ballots/verdicts to MBT's signal CSV and (when MBT + MT5 are
available) runs MBT's backtest to score them. No hosted leaderboard, no weight
adaptation — that is premium.
"""
