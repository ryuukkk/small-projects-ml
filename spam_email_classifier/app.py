from flask import Flask, request, render_template
import pickle
import numpy as np
import re
from collections import Counter
from html import unescape
from sklearn.base import BaseEstimator, TransformerMixin
from scipy.sparse import csr_matrix
import urlextract
import nltk
from email import policy
from email.parser import BytesParser

# Ensure the necessary NLTK resources are available
nltk.download('punkt', quiet=True)

# Custom transformers

class EmailToWordCounterTransformer(BaseEstimator, TransformerMixin):
    def __init__(self, strip_headers=True, lower_case=True,
                 remove_punctuation=True, replace_urls=True,
                 replace_numbers=True, stemming=True):
        self.strip_headers = strip_headers
        self.lower_case = lower_case
        self.remove_punctuation = remove_punctuation
        self.replace_urls = replace_urls
        self.replace_numbers = replace_numbers
        self.stemming = stemming
        self.url_extractor = urlextract.URLExtract()
        self.stemmer = nltk.PorterStemmer()
        
    def __setstate__(self, state):
        self.__dict__.update(state)
        self.url_extractor = urlextract.URLExtract()
        self.stemmer = nltk.PorterStemmer()

    def fit(self, X, y=None):
        return self

    def transform(self, X, y=None):
        X_transformed = []
        for email in X:
            email_obj = BytesParser(policy=policy.default).parsebytes(email.encode('utf-8'))
            text = self.email_to_text(email_obj) or ""
            if self.lower_case:
                text = text.lower()
            if self.replace_urls:
                urls = list(set(self.url_extractor.find_urls(text)))
                urls.sort(key=lambda url: len(url), reverse=True)
                for url in urls:
                    text = text.replace(url, " URL ")
            if self.replace_numbers:
                text = re.sub(r'\d+(?:\.\d*)?(?:[eE][+-]?\d+)?', 'NUMBER', text)
            if self.remove_punctuation:
                text = re.sub(r'\W+', ' ', text, flags=re.M)
            word_counts = Counter(text.split())
            if self.stemming:
                stemmed_word_counts = Counter()
                for word, count in word_counts.items():
                    stemmed_word = self.stemmer.stem(word)
                    stemmed_word_counts[stemmed_word] += count
                word_counts = stemmed_word_counts
            X_transformed.append(word_counts)
        return np.array(X_transformed)
    
    def email_to_text(self, email):
        html = None
        for part in email.walk():
            ctype = part.get_content_type()
            if not ctype in ("text/plain", "text/html"):
                continue
            try:
                content = part.get_content()
            except:  # in case of encoding issues
                content = str(part.get_payload())
            if ctype == "text/plain":
                return content
            else:
                html = content
        if html:
            return self.html_to_plain_text(html)
    
    def html_to_plain_text(self, html):
        text = re.sub(r'<head.*?>.*?</head>', '', html, flags=re.M | re.S | re.I)
        text = re.sub(r'<a\s.*?>', ' HYPERLINK ', text, flags=re.M | re.S | re.I)
        text = re.sub(r'<.*?>', '', text, flags=re.M | re.S)
        text = re.sub(r'(\s*\n)+', '\n', text, flags=re.M | re.S)
        return unescape(text)

class WordCounterToVectorTransformer(BaseEstimator, TransformerMixin):
    def __init__(self, vocabulary_size=1000):
        self.vocabulary_size = vocabulary_size

    def fit(self, X, y=None):
        total_count = Counter()
        for word_count in X:
            for word, count in word_count.items():
                total_count[word] += min(count, 10)
        most_common = total_count.most_common()[:self.vocabulary_size]
        self.vocabulary_ = {word: index + 1
                            for index, (word, count) in enumerate(most_common)}
        return self

    def transform(self, X, y=None):
        rows = []
        cols = []
        data = []
        for row, word_count in enumerate(X):
            for word, count in word_count.items():
                rows.append(row)
                cols.append(self.vocabulary_.get(word, 0))
                data.append(count)
        return csr_matrix((data, (rows, cols)),
                          shape=(len(X), self.vocabulary_size + 1))

# Flask app

app = Flask(__name__)

# Load the pre-trained models
with open("saved_models/preprocess_pipeline.pkl", "rb") as f:
    preprocess_pipeline = pickle.load(f)

with open("saved_models/spam_classifier.pkl", "rb") as f:
    model = pickle.load(f)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email_text = request.form["email_text"]
        email = [email_text]  # Wrapping it in a list for processing
        email_preprocessed = preprocess_pipeline.transform(email)
        prediction = model.predict(email_preprocessed)[0]
        result = "Spam" if prediction == 1 else "Ham"
        return render_template("index.html", result=result, email_text=email_text)
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
