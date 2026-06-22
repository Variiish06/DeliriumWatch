import re

with open("templates/index.html", "r") as f:
    html = f.read()

# Remove Telemetry block
telemetry_pattern = re.compile(r'<!-- TELEMETRY -->\s*<div class="card text-bg-dark telemetry-card mb-3">.*?</div>\s*(?=<!-- RISK RESULT \+ TREND -->)', re.DOTALL)
html = telemetry_pattern.sub('', html)

with open("templates/index.html", "w") as f:
    f.write(html)
