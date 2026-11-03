"""Static marketing content. Edit here rather than in templates."""

PLANS = [
    {
        "id": "starter",
        "name": "Starter",
        "price": "$499",
        "period": "/ month",
        "blurb": "One AI junior engineer for a single team.",
        "features": [
            "1 AI junior employee",
            "GitHub + GitHub Issues integration",
            "Claude Code or pi coding harness",
            "Read-only database access",
            "Email support",
        ],
    },
    {
        "id": "team",
        "name": "Team",
        "price": "$1,999",
        "period": "/ month",
        "blurb": "A pod of AI juniors working your backlog in parallel.",
        "features": [
            "5 AI junior employees",
            "Jira, Linear & GitHub Issues",
            "Warehouse + wiki research tools",
            "AI code review before human review",
            "Slack escalations",
        ],
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price": "Custom",
        "period": "",
        "blurb": "Self-hosted harnesses with your models, your rules.",
        "features": [
            "Unlimited AI employees",
            "Self-hosted / VPC deployment",
            "Custom MCP tool connectors",
            "Audit log + SSO",
            "Dedicated success engineer",
        ],
    },
]

STEPS = [
    (
        "Assign a ticket",
        "Put an epic, story or bug in your project tracker and assign it to deleg8.",
    ),
    (
        "It researches",
        "The AI junior reads your wiki, repos, database and warehouse to understand the work.",
    ),
    ("It plans", "Epics are broken into small tasks, created as tickets, with a plan comment."),
    ("It ships", "Each task is coded with a coding harness, tested, reviewed and opened as a PR."),
    ("It reports", "CI goes green, tickets move to Done and you get an epic summary."),
]

TEAM_SIZES = ["1-10", "11-50", "51-200", "201-1000", "1000+"]
