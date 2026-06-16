"""
End-to-end tests using Playwright against the live dev server (http://localhost:8000).
Run with: uv run pytest tests/test_e2e.py -v

Requires the dev server to be running:
    uv run uvicorn main:app --reload --port 8000
"""
import pytest
from playwright.sync_api import Page, expect


BASE_URL = "http://localhost:8000"
POST_SLUG = "htmx-is-enough"
POST_URL = f"{BASE_URL}/blog/{POST_SLUG}"


# ─── Comments ─────────────────────────────────────────────────────────────────

def test_comment_form_is_visible_on_post_page(page: Page):
  page.goto(POST_URL)
  expect(page.locator("#comments-section")).to_be_visible()
  expect(page.get_by_placeholder("Your name")).to_be_visible()
  expect(page.get_by_placeholder("Leave a comment...")).to_be_visible()
  expect(page.get_by_role("button", name="Post comment")).to_be_visible()


def test_submit_comment_appears_without_page_reload(page: Page):
  page.goto(POST_URL)

  page.get_by_placeholder("Your name").fill("Playwright User")
  page.get_by_placeholder("Leave a comment...").fill("This is a Playwright test comment.")

  # Click submit and wait for HTMX to swap the comments section
  with page.expect_response(f"**/blog/{POST_SLUG}/comments") as resp:
    page.get_by_role("button", name="Post comment").click()

  assert resp.value.status == 200

  # Comment appears in the updated section without a full reload
  expect(page.locator("#comments-section")).to_contain_text("Playwright User")
  expect(page.locator("#comments-section")).to_contain_text("This is a Playwright test comment.")


def test_comment_count_increments_after_submit(page: Page):
  page.goto(POST_URL)

  # Count before
  initial_text = page.locator("#comments-section h2").inner_text()

  page.get_by_placeholder("Your name").fill("Counter Test")
  page.get_by_placeholder("Leave a comment...").fill("Counting comments.")

  with page.expect_response(f"**/blog/{POST_SLUG}/comments"):
    page.get_by_role("button", name="Post comment").click()

  updated_text = page.locator("#comments-section h2").inner_text()
  assert updated_text != initial_text


def test_form_stays_accessible_after_submission(page: Page):
  """After posting a comment, the form remains so the user can post again."""
  page.goto(POST_URL)

  page.get_by_placeholder("Your name").fill("Repeat Poster")
  page.get_by_placeholder("Leave a comment...").fill("First comment.")

  with page.expect_response(f"**/blog/{POST_SLUG}/comments"):
    page.get_by_role("button", name="Post comment").click()

  # Form still present after swap
  expect(page.get_by_placeholder("Your name")).to_be_visible()
  expect(page.get_by_placeholder("Leave a comment...")).to_be_visible()


def test_submit_comment_via_htmx_navigation(page: Page):
  """Navigate to the post via HTMX (from blog list) then submit a comment."""
  page.goto(f"{BASE_URL}/blog")

  # Click the post link — this triggers an HTMX partial swap
  page.get_by_role("link", name="HTMX Is Enough for Most Web Apps").first.click()
  page.wait_for_url(POST_URL)

  expect(page.locator("#comments-section")).to_be_visible()

  page.get_by_placeholder("Your name").fill("HTMX Nav User")
  page.get_by_placeholder("Leave a comment...").fill("Posted after HTMX navigation.")

  with page.expect_response(f"**/blog/{POST_SLUG}/comments"):
    page.get_by_role("button", name="Post comment").click()

  expect(page.locator("#comments-section")).to_contain_text("HTMX Nav User")


def test_empty_author_does_not_submit(page: Page):
  """HTML5 required validation prevents submitting with empty author."""
  page.goto(POST_URL)

  page.get_by_placeholder("Leave a comment...").fill("No author here.")

  # Form should not submit due to required validation on author field
  page.get_by_role("button", name="Post comment").click()

  # No HTMX request fired — comments section unchanged
  expect(page.get_by_placeholder("Your name")).to_be_visible()
  expect(page.locator("#comments-section")).not_to_contain_text("No author here.")
