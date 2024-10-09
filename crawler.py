# crawler.py

import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import time
from collections import Counter
import re
from parsivar import Normalizer, Tokenizer, FindStems
import jdatetime
import logging
import uuid  # For generating unique crawl IDs

logger = logging.getLogger(__name__)

class WebCrawler:
    def __init__(self, start_url, search_words, max_depth=3, case_sensitive=False, exact_match=False, exclude_urls=None, progress_dict=None, crawl_id=None, matched_items=None):
        self.start_url = start_url
        self.search_words = search_words if case_sensitive else [w.lower() for w in search_words]
        self.max_depth = max_depth
        self.case_sensitive = case_sensitive
        self.exact_match = exact_match
        self.exclude_urls = exclude_urls or []
        self.to_visit = asyncio.Queue()
        self.visited = set()
        self.session = None
        self.total_pages = 0
        self.total_matches = 0
        self.results = []
        self.word_frequency = Counter()
        self.start_time = time.time()
        self.all_links = set()
        self.date_patterns = [
            r'(\d{4}/\d{2}/\d{2})',
            r'((?:یکشنبه|دوشنبه|سه‌شنبه|چهارشنبه|پنجشنبه|جمعه|شنبه)\s+\d{1,2}\s+(?:فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+\d{4})'
        ]
        self.persian_digits = {'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'}
        self.persian_months = {
            'فروردین': 1, 'اردیبهشت': 2, 'خرداد': 3, 'تیر': 4, 'مرداد': 5, 'شهریور': 6,
            'مهر': 7, 'آبان': 8, 'آذر': 9, 'دی': 10, 'بهمن': 11, 'اسفند': 12
        }
        self.normalizer = Normalizer()
        self.tokenizer = Tokenizer()
        self.stemmer = FindStems()
        self.stop_crawling = False

        # List of file extensions to ignore
        self.ignored_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.ico',
                                   '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv', '.webm',
                                   '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                                   '.zip', '.rar', '.7z', '.tar', '.gz', '.exe', '.dmg',
                                   '.iso', '.bin', '.apk']

        # Progress tracking
        self.progress = progress_dict if progress_dict is not None else {}
        self.crawl_id = crawl_id if crawl_id is not None else str(uuid.uuid4())

        # Shared list to store matched items
        self.matched_items = matched_items if matched_items is not None else []

        # Event to control pausing and resuming
        self.pause_event = asyncio.Event()
        self.pause_event.set()  # Start in running state

    def pause(self):
        self.pause_event.clear()
        logger.info("Crawler paused.")

    def resume(self):
        self.pause_event.set()
        logger.info("Crawler resumed.")

    def stop(self):
        self.stop_crawling = True
        self.pause_event.set()  # Ensure any waiting workers can exit
        logger.info("Crawler stopped.")

    async def crawl(self):
        workers = []
        try:
            conn = aiohttp.TCPConnector(limit_per_host=10)
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(connector=conn, timeout=timeout) as self.session:
                await self.to_visit.put((self.start_url, 0))
                self.update_progress()  # Initialize progress
                workers = [asyncio.create_task(self.worker()) for _ in range(10)]  # Adjust the number of workers as needed
                while not self.stop_crawling and (not self.to_visit.empty() or any(not w.done() for w in workers)):
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in crawl method: {str(e)}")
        finally:
            for w in workers:
                w.cancel()
            duration = time.time() - self.start_time

            # Ensure 'duration' is always set
            analytics = {
                "total_pages": self.total_pages,
                "total_matches": self.total_matches,
                "word_frequency": self.word_frequency.most_common(20),
                "duration": duration,
                "total_links": len(self.all_links)
            }
            return self.results, analytics, list(self.all_links)

    async def worker(self):
        try:
            while not self.stop_crawling:
                await self.pause_event.wait()  # Wait if paused
                if self.stop_crawling:
                    break
                if self.to_visit.empty():
                    await asyncio.sleep(0.1)
                    continue
                item = await self.to_visit.get()
                if item is None:
                    self.to_visit.task_done()
                    break
                url, depth = item
                await self.process_url(url, depth)
                self.to_visit.task_done()
        except asyncio.CancelledError:
            pass  # Handle cancellation
        except Exception as e:
            logger.error(f"Error in worker: {str(e)}")

    async def process_url(self, url, depth):
        if self.stop_crawling:
            return
        if url in self.visited or depth > self.max_depth or any(exclude in url for exclude in self.exclude_urls):
            return

        # Ignore URLs with certain file extensions
        parsed_url = urlparse(url)
        if any(parsed_url.path.lower().endswith(ext) for ext in self.ignored_extensions):
            logger.info(f"Skipping binary file: {url}")
            return

        self.visited.add(url)
        self.total_pages += 1
        self.update_progress()

        try:
            async with self.session.get(url) as response:
                content_type = response.headers.get('Content-Type', '').lower()
                if not content_type.startswith('text/html'):
                    logger.info(f"Skipping non-HTML content: {url} (Content-Type: {content_type})")
                    return

                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')

                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)

                normalized_text = self.normalizer.normalize(text)
                matches = self.find_matches(normalized_text)

                if matches:
                    self.total_matches += len(matches)
                    date = self.extract_date(text)
                    summary = self.summarize_text(normalized_text)
                    result = {"url": url, "matches": matches, "date": date, "summary": summary}
                    self.results.append(result)
                    self.matched_items.append(result)  # Add to shared matched items list
                    for match in matches:
                        self.word_frequency[match] += 1

                if depth < self.max_depth:
                    links = soup.find_all('a', href=True)
                    for link in links:
                        new_url = urljoin(url, link['href'])
                        new_parsed_url = urlparse(new_url)
                        if any(new_parsed_url.path.lower().endswith(ext) for ext in self.ignored_extensions):
                            continue  # Skip binary files
                        if new_parsed_url.netloc == urlparse(self.start_url).netloc:
                            if new_url not in self.visited and not any(exclude in new_url for exclude in self.exclude_urls):
                                await self.to_visit.put((new_url, depth + 1))
                self.update_progress()
        except Exception as e:
            logger.error(f"Error crawling {url}: {str(e)}")

    def find_matches(self, text):
        matches = []
        search_text = text if self.case_sensitive else text.lower()
        for word in self.search_words:
            word_to_search = word if self.case_sensitive else word.lower()
            if self.exact_match:
                if word_to_search in search_text:
                    matches.append(word)
            else:
                if re.search(r'\b' + re.escape(word_to_search) + r'\b', search_text):
                    matches.append(word)
        return matches

    def extract_date(self, text):
        for pattern in self.date_patterns:
            match = re.search(pattern, text)
            if match:
                persian_date = match.group(1)
                return self.convert_persian_date(persian_date)
        return None

    def convert_persian_date(self, persian_date):
        try:
            for persian_digit, english_digit in self.persian_digits.items():
                persian_date = persian_date.replace(persian_digit, english_digit)

            if '/' in persian_date:
                jdate = jdatetime.datetime.strptime(persian_date, '%Y/%m/%d')
            else:
                parts = persian_date.split()
                day = int(parts[-3])
                month = self.persian_months[parts[-2]]
                year = int(parts[-1])
                jdate = jdatetime.datetime(year, month, day)

            gdate = jdate.togregorian()
            return gdate.strftime('%Y-%m-%d')
        except Exception as e:
            logger.error(f"Error converting Persian date: {e}")
            return persian_date

    def summarize_text(self, text, num_sentences=3):
        sentences = self.tokenizer.tokenize_sentences(text)
        words = self.tokenizer.tokenize_words(text)
        stemmed_words = [self.stemmer.convert_to_stem(word) for word in words]
        word_freq = Counter(stemmed_words)

        sentence_scores = {}
        for sentence in sentences:
            sentence_words = self.tokenizer.tokenize_words(sentence)
            for word in sentence_words:
                stemmed_word = self.stemmer.convert_to_stem(word)
                if stemmed_word in word_freq:
                    if sentence not in sentence_scores:
                        sentence_scores[sentence] = word_freq[stemmed_word]
                    else:
                        sentence_scores[sentence] += word_freq[stemmed_word]

        summary_sentences = sorted(sentence_scores, key=sentence_scores.get, reverse=True)[:num_sentences]
        summary = ' '.join(summary_sentences)
        return summary

    def update_progress(self):
        self.progress[self.crawl_id] = {
            'pages_crawled': self.total_pages,
            'pages_to_visit': self.to_visit.qsize(),
            'total_matches': self.total_matches
        }
