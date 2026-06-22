with open("templates/index.html", "r") as f:
    text = f.read()

text = text.replace("card text-bg-dark-header", "card-header")
text = text.replace("card text-bg-dark-body", "card-body")
text = text.replace("card-glass", "card text-bg-dark")
text = text.replace("card-glass-header", "card-header")
text = text.replace("card-glass-body", "card-body")
text = text.replace("input-glass", "")
text = text.replace("btn-glow", "")

with open("templates/index.html", "w") as f:
    f.write(text)
