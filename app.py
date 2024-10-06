from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, jsonify
import asyncio
from crawler import WebCrawler
from forms import CrawlForm
import io
import csv
import logging
from flask_executor import Executor
import uuid  # For generating unique crawl IDs
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Replace with your own secret key

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory storage for results (for simplicity)
stored_results = {}
stored_analytics = {}
stored_links = {}
crawlers = {}
matched_items_dict = {}  # Dictionary to store matched items per crawl

# Initialize Flask-Executor
executor = Executor(app)

@app.route('/', methods=['GET', 'POST'])
def index():
    form = CrawlForm()
    if form.validate_on_submit():
        # Extract data from form
        url = form.url.data
        words = [word.strip() for word in form.words.data.split(',')]
        exclude_urls = [url.strip() for url in form.exclude_urls.data.split(',')] if form.exclude_urls.data else []
        depth = form.depth.data
        case_sensitive = form.case_sensitive.data
        exact_match = form.exact_match.data

        # Generate a unique crawl ID
        crawl_id = str(uuid.uuid4())
        session['crawl_id'] = crawl_id

        # Create shared progress dictionary and matched items list
        progress = {}
        matched_items = []

        # Run the crawler in a background thread
        def run_crawler():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            crawler = WebCrawler(
                start_url=url,
                search_words=words,
                max_depth=depth,
                case_sensitive=case_sensitive,
                exact_match=exact_match,
                exclude_urls=exclude_urls,
                progress_dict=progress,
                crawl_id=crawl_id,
                matched_items=matched_items
            )
            crawlers[crawl_id] = crawler
            matched_items_dict[crawl_id] = matched_items  # Store matched items list
            results, analytics, all_links = loop.run_until_complete(crawler.crawl())

            # Store results in memory
            stored_results[crawl_id] = results
            stored_analytics[crawl_id] = analytics
            stored_links[crawl_id] = all_links

            # Remove crawler from active crawlers
            crawlers.pop(crawl_id, None)
            matched_items_dict.pop(crawl_id, None)

        executor.submit(run_crawler)

        # Redirect to progress page
        return redirect(url_for('progress'))
    return render_template('index.html', form=form)

@app.route('/progress')
def progress():
    crawl_id = session.get('crawl_id')
    if not crawl_id:
        return redirect(url_for('index'))
    return render_template('progress.html')

@app.route('/progress_status')
def progress_status():
    crawl_id = session.get('crawl_id')
    if not crawl_id:
        return jsonify({'status': 'No active crawl.'})

    crawler = crawlers.get(crawl_id)
    if not crawler:
        return jsonify({'status': 'Completed'})

    progress = crawler.progress.get(crawl_id, {})

    return jsonify({
        'status': 'Crawling',
        'pages_crawled': progress.get('pages_crawled', 0),
        'pages_to_visit': progress.get('pages_to_visit', 0),
        'total_matches': progress.get('total_matches', 0)
    })

@app.route('/matched_items')
def matched_items():
    crawl_id = session.get('crawl_id')
    if not crawl_id:
        return jsonify({'status': 'No active crawl.', 'matched_items': []})

    items = matched_items_dict.get(crawl_id, [])
    # Return the latest matched items
    return jsonify({
        'status': 'Crawling',
        'matched_items': items
    })

@app.route('/results')
def results():
    crawl_id = session.get('crawl_id')
    if not crawl_id:
        flash('No crawl session found.', 'error')
        return redirect(url_for('index'))

    results = stored_results.get(crawl_id, [])
    analytics = stored_analytics.get(crawl_id)

    if not analytics:
        logger.error('Analytics data not found.')
        flash('Analytics data not found.', 'error')
        # Provide default analytics data to prevent errors
        analytics = {
            "total_pages": 0,
            "total_matches": 0,
            "word_frequency": [],
            "duration": 0,
            "total_links": 0
        }

    return render_template('results.html', results=results, analytics=analytics)

@app.route('/download/<file_type>')
def download(file_type):
    crawl_id = session.get('crawl_id')
    if not crawl_id:
        flash('No crawl session found.', 'error')
        return redirect(url_for('index'))

    csv_data = io.StringIO()
    writer = csv.writer(csv_data)

    if file_type == 'domains':
        domains = set(urlparse(link).netloc for link in stored_links.get(crawl_id, []))
        writer.writerow(['Domain'])
        for domain in domains:
            writer.writerow([domain])
        filename = 'unique_domains.csv'
    elif file_type == 'urls':
        urls = [result['url'] for result in stored_results.get(crawl_id, [])]
        writer.writerow(['URL'])
        for url in urls:
            writer.writerow([url])
        filename = 'crawled_urls.csv'
    elif file_type == 'dates':
        dates = [result['date'] or 'Not found' for result in stored_results.get(crawl_id, [])]
        writer.writerow(['Date'])
        for date in dates:
            writer.writerow([date])
        filename = 'release_dates.csv'
    elif file_type == 'matches':
        results = stored_results.get(crawl_id, [])
        writer.writerow(['URL', 'Matches', 'Date', 'Summary'])
        for result in results:
            writer.writerow([
                result['url'],
                ', '.join(result['matches']),
                result['date'] or 'Not found',
                result['summary']
            ])
        filename = 'matched_items.csv'
    else:
        flash('Invalid file type requested.', 'error')
        return redirect(url_for('results'))

    csv_data.seek(0)
    return send_file(
        io.BytesIO(csv_data.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
