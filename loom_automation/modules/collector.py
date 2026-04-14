from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import List, Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import NoSuchWindowException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from pydantic import BaseModel, Field

from loom_automation.models import MeetingMetadata
from loom_automation.prompt_routing import title_matches_keywords

logger = logging.getLogger(__name__)


class CollectedVideo(BaseModel):
    loom_video_id: str
    source_url: str
    title: str
    collected_at: datetime
    transcript_text: Optional[str] = None
    audio_source_path: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


@dataclass
class LoomCollector:
    """Collector for discovering new Loom videos and pulling first-level metadata."""

    use_selenium_fallback: bool = False
    library_url: str = "https://www.loom.com/looms/videos"
    loom_title_include_keywords: str = ""
    loom_title_exclude_keywords: str = ""
    loom_email: str | None = None
    loom_password: str | None = None
    headless: bool = True
    chrome_binary: str | None = None
    chromedriver_path: str | None = None
    chrome_user_data_dir: str | None = None
    chrome_window_size: str = "1600,1200"
    chrome_extra_args: str = ""

    def collect_from_manual_input(
        self,
        loom_video_id: str,
        source_url: str,
        title: str,
        transcript_text: str | None = None,
        tags: list[str] | None = None,
    ) -> CollectedVideo:
        return CollectedVideo(
            loom_video_id=loom_video_id,
            source_url=source_url,
            title=title,
            collected_at=datetime.utcnow(),
            transcript_text=transcript_text,
            tags=tags or [],
        )

    def to_meeting_metadata(self, video: CollectedVideo, meeting_type: str = "discord-sync") -> MeetingMetadata:
        return MeetingMetadata(
            loom_video_id=video.loom_video_id,
            source_url=video.source_url,
            title=video.title,
            meeting_type=meeting_type,
            recorded_at=video.collected_at,
            participants=[],
        )

    def collect_from_local_file(
        self,
        file_path: str,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> CollectedVideo:
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Local video file not found: {path}")

        return CollectedVideo(
            loom_video_id=f"local-{path.stem}",
            source_url=str(path),
            title=title or path.stem,
            collected_at=datetime.utcnow(),
            audio_source_path=str(path),
            tags=tags or ["local-file"],
        )

    def collect_from_folder(
        self,
        folder_path: str,
        tags: list[str] | None = None,
    ) -> list[CollectedVideo]:
        folder = Path(folder_path).expanduser().resolve()
        if not folder.exists() or not folder.is_dir():
            raise FileNotFoundError(f"Local folder not found: {folder}")

        supported_suffixes = {".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav", ".m4a"}
        items = []
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in supported_suffixes:
                items.append(
                    CollectedVideo(
                        loom_video_id=f"local-{path.stem}",
                        source_url=str(path),
                        title=path.stem,
                        collected_at=datetime.utcfromtimestamp(path.stat().st_mtime),
                        audio_source_path=str(path),
                        tags=tags or ["local-folder"],
                    )
                )
        return items

    def collect_new_loom_videos(
        self,
        limit: int,
        known_video_ids: set[str] | None = None,
        known_urls: set[str] | None = None,
        primary_text_query: str | None = None,
        primary_date_query: date | None = None,
        search_results_limit: int = 10,
        title_include_keywords: list[str] | None = None,
        title_exclude_keywords: list[str] | None = None,
        recorded_date_from: date | None = None,
        recorded_date_to: date | None = None,
    ) -> list[CollectedVideo]:
        known_video_ids = known_video_ids or set()
        known_urls = known_urls or set()
        if not self.loom_email or not self.loom_password:
            raise ValueError("LOOM_EMAIL and LOOM_PASSWORD are required for automatic Loom collection.")

        driver = self._create_driver()
        wait = WebDriverWait(driver, 20)
        try:
            self._login(driver, wait)
            driver.get(self._normalize_library_url())
            wait.until(lambda d: "loom.com" in d.current_url)
            search_query = self._build_search_query(primary_text_query, primary_date_query)
            links = self._extract_library_links(
                driver,
                wait,
                search_query=search_query,
                search_results_limit=search_results_limit,
            )

            results: list[CollectedVideo] = []
            for link in links:
                video_id = self._parse_video_id(link)
                if video_id in known_video_ids or link in known_urls:
                    continue

                try:
                    transcript_text, title = self._extract_transcript(driver, wait, link)
                except Exception as exc:
                    logger.warning("Skipping Loom video %s after transcript extraction error: %s", link, exc)
                    continue
                if not transcript_text:
                    continue
                resolved_title = title or video_id
                recorded_at = self._infer_recorded_at(resolved_title)
                if not self._should_collect_title(
                    resolved_title,
                    title_include_keywords=title_include_keywords,
                    title_exclude_keywords=title_exclude_keywords,
                ):
                    continue
                if not self._matches_recorded_date(recorded_at, recorded_date_from, recorded_date_to):
                    continue

                results.append(
                    CollectedVideo(
                        loom_video_id=video_id,
                        source_url=link,
                        title=resolved_title,
                        collected_at=recorded_at or datetime.utcnow(),
                        transcript_text=transcript_text,
                        tags=["loom-auto"],
                    )
                )
                if len(results) >= limit:
                    break

            return results
        finally:
            self._dispose_driver(driver)

    def _create_driver(self):
        last_error: Exception | None = None
        for attempt in range(2):
            profile_dir, should_cleanup = self._resolve_profile_dir()
            try:
                options = self._build_chrome_options(profile_dir)
                service = Service(self._resolve_chromedriver_path())
                driver = webdriver.Chrome(service=service, options=options)
                setattr(driver, "_aicallorder_profile_dir", profile_dir)
                setattr(driver, "_aicallorder_cleanup_profile_dir", should_cleanup)
                return driver
            except Exception as exc:
                last_error = exc
                if should_cleanup:
                    self._cleanup_profile_dir(profile_dir)
                if attempt == 0 and self._is_retryable_startup_error(exc):
                    logger.warning("Retrying Chrome startup after transient browser failure: %s", exc)
                    time.sleep(1)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("Chrome driver failed to start.")

    def _build_chrome_options(self, profile_dir: str) -> Options:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--window-size={self.chrome_window_size or '1600,1200'}")
        options.add_argument("--remote-debugging-port=0")
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-extensions")
        options.add_argument("--password-store=basic")
        options.add_argument("--lang=en-US")
        options.add_experimental_option(
            "prefs",
            {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.default_content_setting_values.notifications": 2,
            },
        )
        browser_binary = self._detect_browser_binary()
        if browser_binary:
            options.binary_location = browser_binary
        for extra_arg in self._parse_extra_args():
            options.add_argument(extra_arg)
        return options

    def _resolve_chromedriver_path(self) -> str:
        explicit_driver = self.chromedriver_path or os.environ.get("CHROMEDRIVER_PATH")
        if explicit_driver and os.path.exists(explicit_driver):
            return explicit_driver

        candidates = [
            r"C:\WebDriver\bin\chromedriver.exe",
            r"C:\Program Files\ChromeDriver\chromedriver.exe",
            "/usr/local/bin/chromedriver",
            "/usr/bin/chromedriver",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

        resolved = shutil.which("chromedriver")
        if resolved:
            return resolved

        return ChromeDriverManager().install()

    def _dispose_driver(self, driver) -> None:
        profile_dir = getattr(driver, "_aicallorder_profile_dir", None)
        should_cleanup = bool(getattr(driver, "_aicallorder_cleanup_profile_dir", False))
        try:
            driver.quit()
        except Exception:
            pass
        if should_cleanup:
            self._cleanup_profile_dir(profile_dir)

    def _cleanup_profile_dir(self, profile_dir: str | None) -> None:
        if not profile_dir:
            return
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

    def _is_retryable_startup_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "devtoolsactiveport",
                "chrome failed to start",
                "session not created",
                "target window already closed",
            )
        )

    def _login(self, driver, wait: WebDriverWait) -> None:
        driver.get("https://www.loom.com/login")
        email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
        email_input.clear()
        email_input.send_keys(self.loom_email)
        continue_with_atlassian = None
        try:
            continue_with_atlassian = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Continue with Atlassian')]"))
            )
        except Exception:
            try:
                email_input.send_keys(Keys.RETURN)
            except Exception:
                pass

        if continue_with_atlassian is not None:
            driver.execute_script("arguments[0].click();", continue_with_atlassian)

        self._wait_for_known_login_context(driver, timeout_seconds=30)

        if "atlassian.com" in self._safe_current_url(driver):
            username_input = wait.until(EC.presence_of_element_located((By.NAME, "username")))
            current_username = (username_input.get_attribute("value") or "").strip()
            if not current_username:
                try:
                    username_input.clear()
                except Exception:
                    driver.execute_script("arguments[0].value = '';", username_input)
                username_input.send_keys(self.loom_email)

            self._submit_current_form(driver, wait)
            password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
            try:
                password_input.click()
            except Exception:
                pass
            try:
                password_input.clear()
            except Exception:
                driver.execute_script("arguments[0].value = '';", password_input)
            try:
                password_input.send_keys(self.loom_password)
            except Exception:
                self._set_input_value(driver, password_input, self.loom_password)
            self._submit_current_form(driver, wait)
        else:
            password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
            try:
                password_input.clear()
            except Exception:
                driver.execute_script("arguments[0].value = '';", password_input)
            try:
                password_input.send_keys(self.loom_password)
            except Exception:
                self._set_input_value(driver, password_input, self.loom_password)
            self._submit_current_form(driver, wait)

        try:
            self._wait_for_library_page(driver, timeout_seconds=45)
        except Exception:
            driver.get(self._normalize_library_url())
            self._wait_for_library_page(driver, timeout_seconds=45)

    def _extract_library_links(
        self,
        driver,
        wait: WebDriverWait,
        *,
        search_query: str | None = None,
        search_results_limit: int = 10,
    ) -> list[str]:
        driver.get(self._normalize_library_url())
        wait.until(lambda d: self._is_library_url(self._safe_current_url(d)) and "Videos" in d.title)
        try:
            wait.until(
                lambda d: len(
                    d.execute_script(
                        """
                        const anchors = Array.from(document.querySelectorAll('a[href]'));
                        return anchors.filter(a =>
                          (a.href || '').includes('loom.com/share/') ||
                          String(a.className || '').includes('video-card_videoCardLink')
                        ).map(a => a.href);
                        """
                    )
                )
                > 0
            )
        except Exception:
            pass
        if search_query:
            searched_links = self._search_library_links(
                driver,
                wait,
                search_query=search_query,
                search_results_limit=search_results_limit,
            )
            if searched_links:
                return searched_links
        driver.execute_script("window.scrollTo(0, 0);")
        previous_count = -1
        stable_rounds = 0
        hrefs: list[str] = []
        for _ in range(12):
            hrefs = driver.execute_script(
                """
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors
                  .filter(a =>
                    (a.href || '').includes('loom.com/share/') ||
                    (a.className || '').includes('video-card_videoCardLink')
                  )
                  .map(a => a.href);
                """
            )
            current_count = len(hrefs)
            if current_count == previous_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
            if stable_rounds >= 2:
                break
            previous_count = current_count
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.execute_script("return document.body.scrollHeight") > 0
                )
            except Exception:
                pass
        deduped = []
        seen = set()
        for href in hrefs:
            if href not in seen:
                seen.add(href)
                deduped.append(href)
        return deduped

    def _search_library_links(
        self,
        driver,
        wait: WebDriverWait,
        *,
        search_query: str,
        search_results_limit: int,
    ) -> list[str]:
        base_url = self._normalize_library_url()
        search_input = None
        selectors = [
            (By.CSS_SELECTOR, "input[placeholder*='Search']"),
            (By.CSS_SELECTOR, "input[placeholder*='search']"),
            (By.CSS_SELECTOR, "input[type='search']"),
            (By.XPATH, "//input[contains(@placeholder, 'Search')]"),
            (By.XPATH, "//input[contains(@placeholder, 'search')]"),
        ]
        for by, selector in selectors:
            try:
                search_input = wait.until(EC.presence_of_element_located((by, selector)))
                break
            except Exception:
                continue

        if search_input is None:
            return []

        try:
            search_input.click()
        except Exception:
            pass
        visible_inputs = [
            element
            for element in driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='Search'], input[placeholder*='search'], input[type='search']")
            if element.is_displayed()
        ]
        if visible_inputs:
            search_input = visible_inputs[-1]
        try:
            search_input.send_keys(Keys.CONTROL, "a")
            search_input.send_keys(Keys.DELETE)
        except Exception:
            driver.execute_script("arguments[0].value = '';", search_input)
        try:
            search_input.send_keys(search_query)
            search_input.send_keys(Keys.RETURN)
        except Exception:
            self._set_search_input_value(driver, search_input, search_query)
            try:
                search_input.send_keys(Keys.RETURN)
            except Exception:
                pass

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.typeahead_result_oGp")))
        except Exception:
            return []

        hrefs: list[str] = []
        seen_labels: set[str] = set()
        max_items = max(1, search_results_limit)

        for index in range(max_items):
            results = [
                item for item in driver.find_elements(By.CSS_SELECTOR, "li.typeahead_result_oGp") if item.is_displayed()
            ]
            if index >= len(results):
                break

            label = (results[index].text or "").strip()
            if label in seen_labels:
                continue
            seen_labels.add(label)

            try:
                results[index].click()
            except Exception:
                driver.execute_script("arguments[0].click();", results[index])

            try:
                wait.until(lambda d: d.current_url != base_url)
            except Exception:
                break

            current_url = driver.current_url
            if "loom.com/share/" in current_url:
                hrefs.append(current_url)

            driver.get(base_url)
            wait.until(lambda d: "/looms/videos" in d.current_url)

            search_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Search']")))
            try:
                search_input.click()
            except Exception:
                pass
            visible_inputs = [
                element
                for element in driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='Search'], input[placeholder*='search'], input[type='search']")
                if element.is_displayed()
            ]
            if visible_inputs:
                search_input = visible_inputs[-1]
            try:
                search_input.send_keys(Keys.CONTROL, "a")
                search_input.send_keys(Keys.DELETE)
                search_input.send_keys(search_query)
                search_input.send_keys(Keys.RETURN)
            except Exception:
                self._set_search_input_value(driver, search_input, search_query)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "li.typeahead_result_oGp")))
            except Exception:
                break

        deduped: list[str] = []
        seen_hrefs: set[str] = set()
        for href in hrefs:
            if href not in seen_hrefs:
                seen_hrefs.add(href)
                deduped.append(href)
        return deduped

    def _set_search_input_value(self, driver, element, value: str) -> None:
        driver.execute_script(
            """
            const element = arguments[0];
            const value = arguments[1];
            if ('value' in element) {
              element.focus();
              element.value = value;
              element.dispatchEvent(new Event('input', { bubbles: true }));
              element.dispatchEvent(new Event('change', { bubbles: true }));
            } else if (element.isContentEditable) {
              element.focus();
              element.textContent = value;
              element.dispatchEvent(new InputEvent('input', { bubbles: true, data: value, inputType: 'insertText' }));
            }
            """,
            element,
            value,
        )

    def _extract_transcript(self, driver, wait: WebDriverWait, video_url: str) -> tuple[str | None, str | None]:
        driver.get(video_url)
        title = driver.title.replace(" | Loom", "").strip() if driver.title else None

        transcript_button = None
        selectors = [
            (By.XPATH, "//button[@role='tab' and normalize-space()='Transcript']"),
            (By.CSS_SELECTOR, "[data-testid='sidebar-tab-Transcript']"),
            (By.XPATH, "//button[contains(., 'Transcript')]"),
        ]
        for by, selector in selectors:
            try:
                transcript_button = wait.until(EC.element_to_be_clickable((by, selector)))
                break
            except Exception:
                continue

        if transcript_button is None:
            return None, title

        driver.execute_script("arguments[0].click();", transcript_button)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid^='transcript-row-']")))

        transcript_text = driver.execute_script(
            """
            const rows = Array.from(document.querySelectorAll("[data-testid^='transcript-row-']"));
            const chunks = rows
              .map(row => (row.innerText || '').trim())
              .filter(text => text && text.length > 5);
            return chunks.join("\\n");
            """
        )

        cleaned = self._clean_transcript_text(transcript_text)
        return (cleaned or None), title

    def _parse_video_id(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            raise ValueError(f"Unsupported Loom URL: {source_url}")
        return parts[-1]

    def _clean_transcript_text(self, text: str | None) -> str:
        if not text:
            return ""
        lines = [line.strip() for line in text.splitlines()]
        filtered = []
        for line in lines:
            if not line:
                continue
            lowered = line.lower()
            if lowered in {"transcript", "download", "comments"}:
                continue
            filtered.append(line)
        return "\n".join(filtered).strip()

    def _should_collect_title(
        self,
        title: str,
        *,
        title_include_keywords: list[str] | None = None,
        title_exclude_keywords: list[str] | None = None,
    ) -> bool:
        include_keywords = (
            self._parse_keywords(self.loom_title_include_keywords)
            if title_include_keywords is None
            else title_include_keywords
        )
        exclude_keywords = (
            self._parse_keywords(self.loom_title_exclude_keywords)
            if title_exclude_keywords is None
            else title_exclude_keywords
        )
        return title_matches_keywords(title, include_keywords, exclude_keywords)

    def _parse_keywords(self, raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        normalized = raw_value.replace("\n", ",").replace(";", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]

    def _matches_recorded_date(
        self,
        recorded_at: datetime | None,
        recorded_date_from: date | None,
        recorded_date_to: date | None,
    ) -> bool:
        if recorded_date_from is None and recorded_date_to is None:
            return True
        if recorded_at is None:
            return False
        recorded_day = recorded_at.date()
        if recorded_date_from and recorded_day < recorded_date_from:
            return False
        if recorded_date_to and recorded_day > recorded_date_to:
            return False
        return True

    def _infer_recorded_at(self, title: str) -> datetime | None:
        value = (title or "").strip()
        iso_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", value)
        if iso_match:
            try:
                return datetime(
                    year=int(iso_match.group(1)),
                    month=int(iso_match.group(2)),
                    day=int(iso_match.group(3)),
                )
            except ValueError:
                return None

        named_match = re.search(
            r"\b(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
            value,
            flags=re.IGNORECASE,
        )
        if named_match:
            months = {
                "january": 1,
                "february": 2,
                "march": 3,
                "april": 4,
                "may": 5,
                "june": 6,
                "july": 7,
                "august": 8,
                "september": 9,
                "october": 10,
                "november": 11,
                "december": 12,
            }
            try:
                return datetime(
                    year=int(named_match.group(3)),
                    month=months[named_match.group(2).lower()],
                    day=int(named_match.group(1)),
                )
            except ValueError:
                return None
        return None

    def _build_search_query(self, primary_text_query: str | None, primary_date_query: date | None) -> str | None:
        parts: list[str] = []
        if primary_text_query and primary_text_query.strip():
            parts.append(primary_text_query.strip())
        if primary_date_query:
            parts.append(primary_date_query.isoformat())
        query = " ".join(parts).strip()
        return query or None

    def _detect_browser_binary(self) -> str | None:
        explicit_binary = self.chrome_binary or os.environ.get("CHROME_BINARY") or os.environ.get("BROWSER_BINARY")
        if explicit_binary and os.path.exists(explicit_binary):
            return explicit_binary

        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/microsoft-edge",
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
        return None

    def _normalize_library_url(self) -> str:
        if self.library_url.rstrip("/") == "https://www.loom.com/library":
            return "https://www.loom.com/looms/videos"
        return self.library_url

    def _submit_current_form(self, driver, wait: WebDriverWait) -> None:
        selectors = [
            (By.CSS_SELECTOR, "button#login-submit"),
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.XPATH, "//button[contains(., 'Continue')]"),
            (By.XPATH, "//button[contains(., 'Продолжить')]"),
            (By.XPATH, "//button[contains(., 'Войти')]"),
        ]
        self._switch_to_latest_window(driver)
        for by, selector in selectors:
            try:
                candidates = driver.find_elements(by, selector)
            except Exception:
                candidates = []
            for button in candidates:
                try:
                    if not button.is_displayed():
                        continue
                    driver.execute_script("arguments[0].click();", button)
                    return
                except Exception:
                    continue

        try:
            self._switch_to_latest_window(driver)
            active = driver.switch_to.active_element
            active.send_keys(Keys.RETURN)
            return
        except Exception:
            submitted = False
            try:
                submitted = bool(
                    driver.execute_script(
                        """
                        const active = document.activeElement;
                        if (active && active.form) {
                          if (active.form.requestSubmit) {
                            active.form.requestSubmit();
                          } else {
                            active.form.submit();
                          }
                          return true;
                        }
                        const form = document.querySelector('form');
                        if (!form) {
                          return false;
                        }
                        if (form.requestSubmit) {
                          form.requestSubmit();
                        } else {
                          form.submit();
                        }
                        return true;
                        """
                    )
                )
            except Exception:
                submitted = False
            if not submitted:
                raise TimeoutException("Could not submit the current Loom login form.")

    def _set_input_value(self, driver, element, value: str) -> None:
        driver.execute_script(
            """
            const element = arguments[0];
            const value = arguments[1];
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(element, value);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            element,
            value,
        )

    def _wait_for_known_login_context(self, driver, timeout_seconds: int = 30) -> str:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                self._switch_to_latest_window(driver)
                current_url = self._safe_current_url(driver)
                if "atlassian.com" in current_url or "loom.com" in current_url:
                    return current_url
            except Exception as exc:
                last_error = exc
            time.sleep(0.5)
        if last_error:
            raise last_error
        raise TimeoutException("Timed out while waiting for Loom/Atlassian login page.")

    def _wait_for_library_page(self, driver, timeout_seconds: int = 45) -> str:
        deadline = time.time() + timeout_seconds
        last_url = ""
        while time.time() < deadline:
            current_url = self._safe_current_url(driver)
            last_url = current_url
            if self._is_library_url(current_url):
                return current_url
            time.sleep(1)
        raise TimeoutException(f"Timed out while waiting for Loom library page. Last URL: {last_url}")

    def _switch_to_latest_window(self, driver) -> None:
        try:
            handles = driver.window_handles
        except WebDriverException as exc:
            raise NoSuchWindowException(str(exc)) from exc
        if not handles:
            raise NoSuchWindowException("Chrome window is no longer available.")
        try:
            current_handle = driver.current_window_handle
        except WebDriverException:
            current_handle = None
        if current_handle not in handles:
            driver.switch_to.window(handles[-1])

    def _safe_current_url(self, driver) -> str:
        self._switch_to_latest_window(driver)
        try:
            return driver.current_url or ""
        except WebDriverException:
            return ""

    def _is_library_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if "loom.com" not in (parsed.netloc or ""):
            return False
        path = (parsed.path or "").rstrip("/").lower()
        return path in {"/library", "/looms/videos"}

    def _resolve_profile_dir(self) -> tuple[str, bool]:
        configured_dir = self.chrome_user_data_dir or os.environ.get("CHROME_USER_DATA_DIR")
        if configured_dir:
            path = Path(configured_dir).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            return str(path), False
        return tempfile.mkdtemp(prefix="aicallorder-chrome-profile-"), True

    def _parse_extra_args(self) -> list[str]:
        raw_value = self.chrome_extra_args or ""
        if not raw_value.strip():
            return []
        return [item.strip() for item in raw_value.replace("\n", ",").split(",") if item.strip()]
