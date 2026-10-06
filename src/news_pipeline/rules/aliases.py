from news_pipeline.config.schema import RulesSection


def remove_exclusions(text: str, rules: RulesSection) -> str:
    """Mask excluded contexts while keeping alias positions stable."""
    text = text.lower()
    exclusions = {value for entry in [*rules.us, *rules.cn] for value in entry.exclude}
    for excluded in sorted(exclusions, key=len, reverse=True):
        if excluded:
            text = text.replace(excluded, " " * len(excluded))
    return text
