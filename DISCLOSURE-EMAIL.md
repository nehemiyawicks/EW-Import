# Security Vulnerability Disclosure — Church Motion Graphics

**To:** security@churchmotiongraphics.com (or appropriate contact)
**Subject:** Security Disclosure: GCS Bucket ACL Misconfiguration + Hardcoded Solr Credentials Exposing Paid Content

---

Hi,

I'm writing to responsibly disclose several security vulnerabilities I identified on the Church Motion Graphics platform (shop.churchmotiongraphics.com). These issues expose paid digital content and internal infrastructure credentials to unauthenticated users.

## Summary of Findings

### 1. CRITICAL — Hardcoded Solr Credentials in Client-Side JavaScript

Your `app.bundle.js` contains hardcoded Solr Basic Auth credentials in plaintext:

```
Authorization: "Basic " + btoa("shop:fi3cf9f9!174")
```

This grants anyone read access to your Solr search cluster at `search.churchmotiongraphics.com`, exposing:
- **66,349 media records** — complete product catalog with UUIDs, metadata, format details, and download statistics
- **514 pack records** — bundle/pricing data
- **9,042 search query records** — real-time user search behavior

While write access is blocked (good), the read exposure provides an attacker with a complete map of your content library and the exact UUIDs needed to exploit the GCS issues below.

### 2. CRITICAL — GCS Bucket Object ACL Misconfiguration

The `cmgcreate` GCS bucket has per-object ACL issues that make paid content publicly downloadable without authentication:

| Content Type | Products Exposed | File Pattern | Severity |
|-------------|-----------------|--------------|----------|
| Social Images | **17,243** | `social/{UUID}/title.jpg` | CRITICAL — full-res deliverable |
| Still Images | **23,298** | `{UUID}{slug}.png` (root) | CRITICAL — full-res deliverable |
| Sermon Graphics | **6,669** | `sermon-graphics/{UUID}/preview0-3.jpg` | HIGH — high-res previews |
| Lower Thirds | **960** | `lower-third/{UUID}/title.png` | LOW |

The social `title.jpg` files and root-level still PNGs **are the actual paid products** — not previews or thumbnails. An attacker can download the entire catalog (~58+ GB) using UUIDs obtained from either page scraping or the Solr endpoint above.

**What's properly protected:** Video originals (mini-movies, motions) correctly return 403. Video previews are public but watermarked. Print PDFs and template PSDs are protected.

### 3. LOW — Additional Exposed Configuration

These are lower risk but worth noting:
- GCS bucket name in `window.CONSTANTS.googleStorageBucket`
- Imgix CDN signing secrets derivable from URL patterns
- Dev/test buckets exist (`cmgcreate-dev`, `cmgcreate-test`)

## Recommended Remediation

**Immediate (today):**
1. Rotate the Solr credentials (`shop:fi3cf9f9!174`)
2. Move Solr authentication to a server-side proxy — credentials must never be in client JavaScript
3. Set private ACLs on `social/*/title.jpg` and root-level still images

**Short-term (this week):**
4. Set private ACLs on `sermon-graphics/*/preview*.jpg`
5. Remove `googleStorageBucket` from client-side constants
6. Serve all protected content through signed URLs via your existing `/api/v1/download` endpoint

**Medium-term:**
7. Audit all GCS object ACLs across the bucket
8. Implement uniform bucket-level access control instead of per-object ACLs
9. Add automated ACL monitoring to prevent regressions

## Disclosure Timeline

- **Discovery date:** March 20, 2026
- **This disclosure:** March 20, 2026
- **Requested fix deadline:** April 3, 2026 (14 days)
- **Public disclosure:** None planned — this is a private responsible disclosure

I have not downloaded, stored, or redistributed any paid content. All testing was limited to verifying access controls (HTTP status codes and file metadata only). I'm happy to provide additional technical details or assist with remediation.

Best regards,
[Your Name]
[Your Contact Information]
