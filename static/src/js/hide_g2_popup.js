/** @odoo-module **/

import { session } from "@web/session";
import { cookie } from "@web/core/browser/cookie";

// Set the g2_review cookie to prevent the OpenEducat G2 review popup from showing
// The cookie name must match: g2_review_${db_name}
const cookieName = `g2_review_${session.db}`;
const nbDays = 365; // Set for 1 year

// Set the cookie to indicate the review has been shown
cookie.set(cookieName, true, nbDays * 24 * 60 * 60, 'required');

// Also ensure the popup container is hidden if it somehow appears
document.addEventListener('DOMContentLoaded', () => {
    const g2Container = document.querySelector('.g2_review_container');
    if (g2Container) {
        g2Container.style.display = 'none';
    }
});
