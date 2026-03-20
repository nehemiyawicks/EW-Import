# Security Vulnerability Disclosure — Church Motion Graphics

**To:** info@ministrybrands.com
**CC:** media@ministrybrands.com
**Subject:** Responsible Security Disclosure — Church Motion Graphics (CMG) Subsidiary

---

Hi Ministry Brands Security/Engineering Team,

I'm a security researcher reaching out to responsibly disclose several vulnerabilities I identified on your subsidiary Church Motion Graphics' platform (shop.churchmotiongraphics.com). I was unable to find a dedicated security contact or security.txt for either CMG or Ministry Brands, so I'm reaching out through this channel.

I want to emphasize upfront: I have not downloaded, stored, or redistributed any paid content, nor have I accessed any customer accounts or private user data.

## Summary of Findings

### 1. Hardcoded Database Credentials in Client-Side JavaScript

Your client-side JavaScript bundle (`app.bundle.js`) contains plaintext credentials for your Solr search database. These credentials are visible to anyone who opens their browser's developer tools or views the page source.

Specifically, the JavaScript contains a Basic Auth header constructed with hardcoded username and password, used for requests to your search infrastructure at `search.churchmotiongraphics.com`.

**Risk:** Anyone with a web browser can extract these credentials. If the Solr instance contains product metadata, UUIDs, pricing, or user search queries, this data could be read by unauthorized parties. This also provides an attacker the information needed to exploit the GCS issue described below.

**Recommendation:** Rotate these credentials immediately and move all Solr authentication behind a server-side API proxy so credentials are never shipped to the browser.

### 2. Google Cloud Storage Bucket — Object ACL Misconfiguration

The GCS bucket serving your content has inconsistent per-object access controls. While some file types are properly protected (video originals, PDFs, PSDs), others appear to be publicly accessible without authentication.

Based on reviewing your publicly available sitemap.xml and page source HTML, I identified that certain file patterns within the bucket respond with HTTP 200 (publicly accessible) rather than 403 (forbidden). The affected file types appear to include full-resolution image deliverables — not just thumbnails or previews.

Product categories that appear to have properly protected originals include: mini-movies, motion backgrounds, and print templates. The watermarked video previews are public but appear intentionally so.

**Risk:** The publicly accessible image files may be the same assets your customers pay for, which would represent significant revenue exposure across potentially tens of thousands of products.

**Recommendation:** Audit all object ACLs in your GCS bucket. Consider migrating to uniform bucket-level access control and serving all paid content exclusively through signed URLs via your existing authenticated download API.

### 3. Additional Configuration Exposure

Your client-side JavaScript and page source also expose several internal configuration values, including:
- The GCS bucket name
- Third-party service API keys
- CDN configuration details

While some of these are lower risk individually, they collectively reduce the effort required for an attacker to map your infrastructure.

**Recommendation:** Review all values exposed in `window.CONSTANTS` and `app.bundle.js` and move any sensitive configuration server-side.

## What I Did and Did Not Do

- I reviewed publicly accessible page source, JavaScript files, and sitemap.xml
- I checked HTTP response codes (200 vs 403) on GCS object URLs constructed from publicly visible information
- I did **not** download, store, or redistribute any paid content
- I did **not** access any user accounts, customer data, or admin interfaces
- I did **not** attempt any write operations, data modification, or service disruption
- I have **not** shared these findings with any third party

## Disclosure Timeline

- **Discovery date:** March 20, 2026
- **This disclosure:** March 20, 2026
- **Requested fix window:** 30 days (April 19, 2026)
- **Public disclosure:** None planned — this is a private responsible disclosure

I'm happy to provide additional technical details, clarify any of these findings, or assist with remediation if that would be helpful. I can be reached at the contact information below.

Best regards,
[Your Name]
[Your Contact Information]
