from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, BooleanField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, URL, NumberRange

class CrawlForm(FlaskForm):
    url = StringField('Website URL', validators=[DataRequired(), URL()], render_kw={"placeholder": "Enter the website URL"})
    words = TextAreaField('Search Word(s)', validators=[DataRequired()], description='Separate multiple words with commas.', render_kw={"placeholder": "Enter words to search, separated by commas"})
    exclude_urls = TextAreaField('Exclude URLs', description='Optional. Separate multiple URLs with commas.', render_kw={"placeholder": "Enter URLs to exclude, separated by commas"})
    depth = IntegerField('Crawl Depth', validators=[DataRequired(), NumberRange(min=1, max=10)], default=3)
    case_sensitive = BooleanField('Case Sensitive Search')
    exact_match = BooleanField('Exact Match Search')
    submit = SubmitField('Start Crawling')
