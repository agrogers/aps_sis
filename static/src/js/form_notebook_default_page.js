/** @odoo-module **/

import { onMounted } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { useService } from "@web/core/utils/hooks";

// 1. Check the field default_notebook_page_per_user on the form's root model for a JSON mapping of user_id to page name
// 2. If not found, check the context for default_notebook_page
// 3. If not found, look for any page with the "default-page" class and use its name
// 4. Set the default page on form load
// 5. Listen for tab changes and update the default_notebook_page_per_user field with the selected page for the current user    

const originalFormSetup = FormController.prototype.setup;

patch(FormController.prototype, {
    setup(...args) {
        if (originalFormSetup) {
            originalFormSetup.call(this, ...args);
        }

        super.setup(...arguments);  // ← must call this first

        onMounted(() => {

            const rootEl = this.el || this.root?.el || document.querySelector(".o_form_view");
            if (!rootEl) {
                return;
            }
            // Return also if there is no notebook control on the form
            const hasNotebook = rootEl.querySelector('.o_notebook_headers, .o_notebook_tabs');
            if (!hasNotebook) {
                return;
            }

            let currentUserId = this.props.context?.uid;
            // const user = useService("user");           // ← this is the way
            // currentUserId = user.userId; 
            
            let pageName = null;
            try {
                const perUserDefaults = this.model.root.data.default_notebook_page_per_user;
                const defaults = JSON.parse(perUserDefaults || '{}');
                pageName = defaults[currentUserId];
            } catch (e) {
                // JSON parse failed
            }
            if (!pageName) {
                pageName = this.props.context?.default_notebook_page;
            }

            if (!pageName) {
                // look for any page with the "default-page" class and use its name
                const defaultPage = rootEl.querySelector('.o_notebook_headers .default-page, .o_notebook_tabs .default-page');
                if (defaultPage) {
                    pageName = defaultPage.getAttribute('name') || defaultPage.getAttribute('data-name');
                }
            }

            // Set default page if specified
            if (pageName) {
                const tab = rootEl.querySelector(
                    `.o_notebook_headers [name="${pageName}"], .o_notebook_tabs [name="${pageName}"], .o_notebook_headers [data-name="${pageName}"], .o_notebook_tabs [data-name="${pageName}"]`
                );
                if (tab && tab.click) {
                    tab.click();
                }
            }

            // Listen for tab changes and update the default_notebook_page_per_user field
            const tabs = rootEl.querySelectorAll('.o_notebook_headers [name], .o_notebook_tabs [name]');
            tabs.forEach(tab => {
                tab.addEventListener('click', () => {
                    const newPageName = tab.getAttribute('name');
                    if (newPageName && this.model && this.model.root) {
                        let currentDefaults = {};
                        try {
                            currentDefaults = JSON.parse(this.model.root.data.default_notebook_page_per_user || '{}');
                        } catch (e) {
                            // JSON parse failed, start with empty object
                        }
                        currentDefaults[currentUserId] = newPageName;
                        this.model.root.update({ default_notebook_page_per_user: JSON.stringify(currentDefaults) });
                    }
                });
            });
        });
    },
});