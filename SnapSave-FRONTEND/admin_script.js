
      const API_BASE =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1"
          ? "http://127.0.0.1:8000"
          : window.location.origin;

      // Role-management: enables RBAC for admin control over user roles
      const ENABLE_ROLE_MANAGEMENT = true;

      const STORAGE_KEY = 'snapsave_admin_token';

      let idToken = null;
      let currentUser = null;

      let activeOrders = [];
      let selectedOrder = null;
      let moderatorsList = [];
      let customersList = [];
      let currentAdminSection = "tickets";
      let selectedHelpUserId = null;

      let backgroundPolling = null;
      // Management login — phone lookup, token, RBAC check
      window.handleProductionLogin = async function () {
        const rawPhone = document.getElementById("login-phone").value.trim();
        const phone = rawPhone.startsWith("+") ? rawPhone : "+91" + rawPhone.replace(/\s/g, "");
        console.log("[LOGIN] Phone entered:", phone);

        if (!phone) {
          console.warn("⚠️ [LOGIN] Phone number is empty");
          showAuthAlert("Please enter a phone number.", "error");
          return;
        }

        const loginBtn = document.querySelector('#phone-login-card .btn');
        if (loginBtn) {
          loginBtn.disabled = true;
          loginBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Logging in...';
        }

        try {
          console.log("📤 [LOGIN] Sending test-token request for OTP SMS to:", phone);
          const response = await fetch(
            `${API_BASE}/api/auth/test-token?phone=${encodeURIComponent(phone)}`,
          );
          const data = await response.json();

          console.log("📥 [LOGIN] Response status:", response.status);
          console.log("📥 [LOGIN] Response data:", data);

          if (!response.ok) {
            throw new Error(data.detail || "Login failed");
          }

          if (!data.idToken) {
            throw new Error("No token received from server.");
          }

          console.log("[LOGIN] Authentication successful, idToken received");
          idToken = data.idToken;
          localStorage.setItem(STORAGE_KEY, idToken);
          await checkUserSession();
        } catch (err) {
          console.error("❌ [LOGIN] Error:", err.message);
          showAuthAlert("Login failed: " + err.message, "error");
          if (loginBtn) {
            loginBtn.disabled = false;
            loginBtn.innerHTML = '<i class="fa-solid fa-sign-in-alt"></i> Login';
          }
        }
      };

      window.handleLogout = function () {
        idToken = null;
        currentUser = null;
        selectedOrder = null;
        clearInterval(backgroundPolling);
        document.body.classList.remove("admin-shell");
        localStorage.removeItem(STORAGE_KEY);
        showLoggedOutView();
      };

      function showLoggedOutView() {
        document.getElementById("auth-section").style.display = "flex";
        document.getElementById("dashboard-header").style.display = "none";
        document.getElementById("dashboard-metrics").style.display = "none";
        document.getElementById("dashboard-main").style.display = "none";
      }

      async function checkUserSession() {
        try {
          console.log("🔍 [SESSION] Checking user session...");
          const me = await apiRequest("/api/auth/me");

          console.log("👤 [SESSION] User data received:", me);
          console.log("👥 [SESSION] User role:", me.role);
          console.log("📱 [SESSION] User phone:", me.phone_number || me.email);

          if (me.role !== "ADMIN" && me.role !== "MODERATOR") {
            console.warn("🚫 [SESSION] Access denied - user is not ADMIN or MODERATOR, role is:", me.role);
            showAuthAlert(
              "Access Denied: Customers cannot view the management console.",
              "error",
            );
            idToken = null;
            return;
          }

          console.log("✅ [SESSION] User has valid role:", me.role);
          currentUser = me;

          if (me.role === "ADMIN") {
            console.log("🔑 [DASHBOARD] Loading ADMIN dashboard");
          } else if (me.role === "MODERATOR") {
            console.log("🛠️ [DASHBOARD] Loading MODERATOR dashboard");
          }

          await startDashboard();
        } catch (err) {
          console.error("❌ [SESSION] Error checking session:", err.message);
          showAuthAlert("Session check failed: " + err.message, "error");
          handleLogout();
        }
      }

      async function startDashboard() {
        setupMetricCards();
        document.getElementById("auth-section").style.display = "none";
        document.getElementById("dashboard-header").style.display = "flex";
        document.getElementById("dashboard-metrics").style.display = "flex";
        document.getElementById("dashboard-main").style.display = "flex";

        document.getElementById("user-phone").innerText =
          currentUser.phone_number || currentUser.email;
        const roleBadge = document.getElementById("user-role");
        roleBadge.innerText = currentUser.role;
        roleBadge.className =
          "role-badge " +
          (currentUser.role === "ADMIN" ? "role-admin" : "role-moderator");

        // Setup role-specific UI
        if (currentUser.role === "ADMIN") {
          document.body.classList.add("admin-shell");
          if (ENABLE_ROLE_MANAGEMENT) {
            const nr = document.getElementById("nav-roles");
            if (nr) nr.style.display = "flex";
          }
          showAdminSection("tickets");
          await loadAdminConfigurations();
        } else {
          showAdminSection("tickets");
        }
        // Always start on queue tab
        switchOrdersTab("queue");

        await loadMetrics();
        await loadQueue();

        // Periodic background polling - only real-time updates (chat, queue, assignments)
        // Metrics are loaded only on Analytics section view and initial dashboard load
        const isAdmin = currentUser.role === "ADMIN";
        clearInterval(backgroundPolling);
        backgroundPolling = setInterval(async () => {
          const tasks = [loadQueue()];
          if (isAdmin)
            tasks.push(pollChat(), pollAdminAssignments(), updateHelpBadge());
          await Promise.all(tasks);
        }, 5000);
      }

      function setSwitches(ids, checked) {
        ids.forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.checked = checked;
        });
      }

      async function loadAdminConfigurations() {
        try {
          // Load Orders Global status
          const orderSettings = await apiRequest("/api/admin/settings/orders");
          setSwitches(
            ["order-global-switch", "order-global-switch-2"],
            orderSettings.orders_enabled,
          );

          // Load Maintenance status
          const maint = await apiRequest("/api/admin/settings/maintenance");
          setSwitches(["maintenance-switch"], maint.maintenance_mode);

          // Load Delivery Config
          try {
            const deliveryConfig = await apiRequest("/api/admin/delivery-config");
            if (deliveryConfig) {
              if(deliveryConfig.zepto !== undefined) document.getElementById("config-zepto").value = deliveryConfig.zepto;
              if(deliveryConfig.blinkit !== undefined) document.getElementById("config-blinkit").value = deliveryConfig.blinkit;
              if(deliveryConfig.swiggy !== undefined) document.getElementById("config-instamart").value = deliveryConfig.swiggy;
              if(deliveryConfig.bigbasket !== undefined) document.getElementById("config-bigbasket").value = deliveryConfig.bigbasket;
            }
          } catch(e) {
            console.log("Failed to load delivery config:", e);
          }

          // Load AI Global status
          try {
            const aiStatus = await apiRequest("/api/admin/settings/ai-status");
            setSwitches(["ai-global-switch"], aiStatus.ai_enabled);
          } catch (e) {}

          // Load assignments dropdown options
          moderatorsList = await apiRequest("/api/admin/moderators");
          await loadAdminAssignments();
        } catch (e) {
          console.log("Admin configs load failure:", e);
        }
      }


      function renderMessages(allMsgs) {
        const stream = document.getElementById("active-chat-stream");
        stream.innerHTML = "";
        
        let msgs = allMsgs.filter(m => m.order_id === selectedOrder.id || !m.order_id);
        
        if (!msgs.length) {
          stream.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:12px;margin-top:20px;">No messages yet.</div>`;
          return;
        }

        msgs.forEach((m) => {
          // implementation continues...
        });
      }

      async function loadAdminAssignments() {
        try {
          customersList = await apiRequest("/api/admin/customers");
          pollAdminAssignments();
        } catch (e) {
          console.log("Error loading customers:", e);
        }
      }

      function pollAdminAssignments() {
        if (!currentUser || currentUser.role !== "ADMIN") return;
        const container = document.getElementById("admin-assignments-list");
        container.innerHTML = "";

        if (customersList.length === 0) {
          container.innerHTML = `<p style="font-size: 12px; color: var(--text-muted); text-align: center;">No customers registered.</p>`;
          return;
        }

        customersList.forEach((c) => {
          const row = document.createElement("div");
          row.className = "assignment-row";

          let options = `<option value="">— Unassigned —</option>`;
          moderatorsList.forEach((m) => {
            options += `<option value="${m.id}" ${c.assigned_moderator_id === m.id ? "selected" : ""}>${m.role}: ${m.phone_number || m.email}</option>`;
          });

          const isAssigned = !!c.assigned_moderator_id;
          row.innerHTML = `
                    <div class="customer-label">
                        <i class="fa-solid fa-user"></i>
                        ${c.phone_number || c.email}
                        ${isAssigned ? '<span style="margin-left:auto;font-size:9px;color:var(--accent-green);font-weight:700;">ASSIGNED</span>' : '<span style="margin-left:auto;font-size:9px;color:var(--text-muted);font-weight:700;">OPEN</span>'}
                    </div>
                    <select class="input-control" style="padding: 6px 10px; font-size: 12px;" onchange="assignCustomer('${c.id}', this.value)">
                        ${options}
                    </select>
                `;
          container.appendChild(row);
        });
      }

      window.assignCustomer = async function (customerId, moderatorId) {
        if (!moderatorId) return;
        try {
          await apiRequest("/api/admin/assign-moderator", "POST", {
            customer_id: customerId,
            moderator_id: moderatorId,
          });
          await loadAdminConfigurations();
          await loadQueue();
        } catch (err) {
          alert("Assignment failed: " + err.message);
        }
      };

      async function applyOrdersToggle(checked) {
        try {
          await apiRequest("/api/admin/settings/orders", "PUT", {
            orders_enabled: checked,
          });
          setSwitches(["order-global-switch", "order-global-switch-2"], checked);
        } catch (err) {
          alert("Order switch toggle failed: " + err.message);
          setSwitches(
            ["order-global-switch", "order-global-switch-2"],
            !checked,
          );
        }
      }
      window.toggleGlobalOrders = () =>
        applyOrdersToggle(document.getElementById("order-global-switch").checked);
      window.toggleGlobalOrders2 = () =>
        applyOrdersToggle(
          document.getElementById("order-global-switch-2").checked,
        );

      window.saveDeliveryConfig = async function() {
        try {
          const thresholds = {
            zepto: parseFloat(document.getElementById("config-zepto").value) || 199,
            blinkit: parseFloat(document.getElementById("config-blinkit").value) || 199,
            swiggy: parseFloat(document.getElementById("config-instamart").value) || 199,
            bigbasket: parseFloat(document.getElementById("config-bigbasket").value) || 299
          };
          await apiRequest("/api/admin/delivery-config", "PUT", { thresholds });
          alert("Delivery Thresholds saved successfully!");
        } catch (err) {
          alert("Failed to save delivery thresholds: " + err.message);
        }
      };

      window.toggleMaintenance = async function () {
        const checked = document.getElementById("maintenance-switch").checked;
        try {
          await apiRequest("/api/admin/settings/maintenance", "PUT", {
            maintenance_mode: checked,
          });
        } catch (err) {
          alert("Maintenance toggle failed: " + err.message);
          document.getElementById("maintenance-switch").checked = !checked;
        }
      };

      window.toggleGlobalAi = async function () {
        const checked = document.getElementById("ai-global-switch").checked;
        try {
          await apiRequest("/api/admin/settings/ai-status", "PUT", {
            ai_enabled: checked,
          });
        } catch (err) {
          alert("AI switch toggle failed: " + err.message);
          document.getElementById("ai-global-switch").checked = !checked;
        }
      };

      window.toggleAiTakeover = async function () {
        if (!selectedOrder) return;
        const checked = document.getElementById("takeover-switch").checked;
        try {
          await apiRequest(`/api/moderator/chat/${selectedOrder.customer_id}/takeover`, "PUT", {
            takeover: checked,
          });
        } catch (err) {
          alert("Takeover toggle failed: " + err.message);
          document.getElementById("takeover-switch").checked = !checked;
        }
      };


      // ── Admin section navigation ──
      window.showAdminSection = function (name) {
        currentAdminSection = name;
        document
          .querySelectorAll(".admin-nav-item")
          .forEach((b) =>
            b.classList.toggle("active", b.dataset.section === name),
          );
        // Exit beta view if it was open
        document.getElementById("beta-program-view").style.display = "none";

        const isTickets = name === "tickets";
        const isAnalytics = name === "analytics";

        // Show/hide workspace and tabs (only for tickets)
        document.getElementById("workspace-container").style.display = isTickets
          ? ""
          : "none";
        document.getElementById("mobile-tab-bar").style.display = isTickets
          ? ""
          : "none";

        // Show/hide admin sections
        document
          .querySelectorAll(".admin-section")
          .forEach((s) => s.classList.remove("active"));
        if (!isTickets) {
          const sec = document.getElementById("section-" + name);
          if (sec) sec.classList.add("active");
        }

        // Load data based on section
        if (name === "customers") loadCustomersAdmin();
        if (name === "help") loadHelpInbox();
        if (name === "roles") loadRolesAdmin();
        if (name === "analytics") loadMetrics();
      };

      // ── Customers section (blacklist) ──
      async function loadCustomersAdmin() {
        const container = document.getElementById("customers-admin-list");
        try {
          const customers = await apiRequest("/api/admin/customers");
          if (!customers.length) {
            container.innerHTML = `<p style="color:var(--text-muted);">No customers registered yet.</p>`;
            return;
          }
          container.innerHTML = "";
          customers.forEach((c) => {
            const row = document.createElement("div");
            row.className = "data-row";
            row.innerHTML = `
              <div class="dr-main">
                <div class="dr-title">
                  <i class="fa-solid fa-user" style="color:var(--accent-purple)"></i>
                  ${c.phone_number || c.email}
                  ${c.is_blacklisted ? '<span class="badge cancelled" style="margin-left:6px;">Blacklisted</span>' : ""}
                </div>
                <div class="dr-sub">${c.is_blacklisted ? "Reason: " + (c.blacklist_reason || "—") : "Active account"}</div>
              </div>
              ${
                c.is_blacklisted
                  ? `<button class="btn btn-secondary" onclick="unblacklist('${c.id}')"><i class="fa-solid fa-unlock"></i> Reinstate</button>`
                  : `<button class="btn btn-danger" onclick="blacklist('${c.id}')"><i class="fa-solid fa-ban"></i> Blacklist</button>`
              }`;
            container.appendChild(row);
          });
        } catch (e) {
          container.innerHTML = `<p style="color:#ef4444;">Failed to load customers: ${e.message}</p>`;
        }
      }
      window.blacklist = async function (userId) {
        const reason = prompt("Reason for blacklisting this customer?") || "";
        try {
          await apiRequest(`/api/admin/customers/${userId}/blacklist`, "PUT", {
            reason,
          });
          loadCustomersAdmin();
        } catch (e) {
          alert("Failed: " + e.message);
        }
      };
      window.unblacklist = async function (userId) {
        try {
          await apiRequest(`/api/admin/customers/${userId}/unblacklist`, "PUT");
          loadCustomersAdmin();
        } catch (e) {
          alert("Failed: " + e.message);
        }
      };

      // ── Help inbox ──
      async function updateHelpBadge() {
        try {
          const threads = await apiRequest("/api/admin/help");
          const openCount = threads.filter((t) => t.open).length;
          const badge = document.getElementById("help-badge");
          if (badge) {
            badge.style.display = openCount ? "flex" : "none";
            badge.innerText = openCount;
          }
        } catch (e) {
          /* non-fatal */
        }
      }

      async function loadHelpInbox() {
        const list = document.getElementById("help-thread-list");
        try {
          const threads = await apiRequest("/api/admin/help");
          const openCount = threads.filter((t) => t.open).length;
          const badge = document.getElementById("help-badge");
          if (badge) {
            badge.style.display = openCount ? "flex" : "none";
            badge.innerText = openCount;
          }
          if (!threads.length) {
            list.innerHTML = `<p style="color:var(--text-muted); padding:10px;">No support requests.</p>`;
            return;
          }
          list.innerHTML = "";
          threads.forEach((t) => {
            const item = document.createElement("div");
            item.className = "queue-card";
            if (t.user_id === selectedHelpUserId) item.classList.add("selected");
            const last = t.messages[t.messages.length - 1];
            item.innerHTML = `
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:13px; font-weight:600;">${t.customer_phone}</span>
                ${t.open ? '<span class="badge pending_review">OPEN</span>' : '<span class="badge delivered">DONE</span>'}
              </div>
              <div style="font-size:11px; color:var(--text-muted); margin-top:4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${last ? last.message : ""}</div>`;
            item.onclick = () => openHelpThread(t);
            list.appendChild(item);
          });
        } catch (e) {
          list.innerHTML = `<p style="color:#ef4444; padding:10px;">${e.message}</p>`;
        }
      }
      let currentHelpThread = null;
      function openHelpThread(t) {
        selectedHelpUserId = t.user_id;
        currentHelpThread = t;
        loadHelpInbox();
        const conv = document.getElementById("help-conversation");
        const bubbles = t.messages
          .map((m) => {
            const isAdmin = m.sender_role === "ADMIN";
            return `<div class="chat-bubble ${isAdmin ? "moderator" : "customer"}" style="max-width:80%;">
              <div class="chat-sender">${isAdmin ? "You (Admin)" : "Customer"}</div>
              <div style="white-space:pre-wrap;">${m.message}</div>
              <div class="chat-timestamp">${new Date(m.created_at + "Z").toLocaleString()}</div>
            </div>`;
          })
          .join("");
        conv.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:10px; margin-bottom:12px;">
            <strong>${t.customer_phone}</strong>
            <button class="btn btn-secondary" style="padding:6px 12px;" onclick="resolveHelp('${t.user_id}')">Mark Resolved</button>
          </div>
          <div style="flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:10px; margin-bottom:12px; max-height:48vh;">${bubbles}</div>
          <div style="display:flex; gap:10px;">
            <input type="text" id="help-reply-input" class="input-control" placeholder="Reply to customer..." style="flex:1;" />
            <button class="btn" style="padding:10px 16px;" onclick="replyHelp('${t.user_id}')"><i class="fa-solid fa-paper-plane"></i></button>
          </div>`;
        const inp = document.getElementById("help-reply-input");
        inp.addEventListener("keypress", (e) => {
          if (e.key === "Enter") replyHelp(t.user_id);
        });
      }
      window.replyHelp = async function (userId) {
        const inp = document.getElementById("help-reply-input");
        const msg = inp.value.trim();
        if (!msg) return;
        try {
          await apiRequest(`/api/admin/help/${userId}/reply`, "POST", {
            message: msg,
          });
          const threads = await apiRequest("/api/admin/help");
          const t = threads.find((x) => x.user_id === userId);
          if (t) openHelpThread(t);
        } catch (e) {
          alert("Failed to reply: " + e.message);
        }
      };
      window.resolveHelp = async function (userId) {
        try {
          await apiRequest(`/api/admin/help/${userId}/resolve`, "PUT");
          loadHelpInbox();
        } catch (e) {
          alert("Failed: " + e.message);
        }
      };

      // ── Roles (hidden) ──
      async function loadRolesAdmin() {
        const container = document.getElementById("roles-admin-list");
        try {
          const users = await apiRequest("/api/admin/users");
          container.innerHTML = "";
          users.forEach((u) => {
            const row = document.createElement("div");
            row.className = "data-row";
            row.innerHTML = `
              <div class="dr-main">
                <div class="dr-title">${u.phone_number || u.email}
                  <span class="role-badge ${u.role === "ADMIN" ? "role-admin" : u.role === "MODERATOR" ? "role-moderator" : ""}" style="margin-left:6px;">${u.role}</span>
                </div>
                <div class="dr-sub">${u.email}</div>
              </div>
              <select class="input-control" style="width:160px; padding:8px 10px; font-size:12px;" onchange="changeRole('${u.id}', this.value)">
                <option value="CUSTOMER" ${u.role === "CUSTOMER" ? "selected" : ""}>Customer</option>
                <option value="MODERATOR" ${u.role === "MODERATOR" ? "selected" : ""}>Moderator</option>
                <option value="ADMIN" ${u.role === "ADMIN" ? "selected" : ""}>Admin</option>
              </select>`;
            container.appendChild(row);
          });
        } catch (e) {
          container.innerHTML = `<p style="color:#ef4444;">${e.message}</p>`;
        }
      }
      window.changeRole = async function (userId, role) {
        try {
          await apiRequest("/api/admin/roles", "PUT", {
            user_id: userId,
            role: role,
          });
          loadRolesAdmin();
        } catch (e) {
          alert("Role change failed: " + e.message);
        }
      };

      // ── Cancel order (admin) ──
      window.cancelOrder = async function () {
        if (!selectedOrder) return;
        if (!confirm("Cancel this order? This cannot be undone.")) return;
        setLoading("btn-cancel-order", true);
        try {
          const res = await apiRequest(
            `/api/admin/orders/${selectedOrder.order_id}/cancel`,
            "PUT",
          );
          selectedOrder.status = res.status;
          await loadQueue();
          renderTicketDetails();
          await pollChat();
        } catch (err) {
          alert("Cancel failed: " + err.message);
        } finally {
          setLoading("btn-cancel-order", false);
        }
      };

      function setupMetricCards() {
        const metricsContainer = document.getElementById("dashboard-metrics");
        if (!metricsContainer) return;
        if (currentUser.role === "ADMIN") {
          metricsContainer.innerHTML = `
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(59, 130, 246, 0.15); color: var(--primary);"><i class="fa-solid fa-cart-shopping"></i></div>
                        <div>
                            <div class="metric-label">Orders Today</div>
                            <div id="metric-orders-today" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(6, 182, 212, 0.15); color: var(--accent-cyan);"><i class="fa-solid fa-clock"></i></div>
                        <div>
                            <div class="metric-label">Pending Review</div>
                            <div id="metric-orders-pending" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(249, 115, 22, 0.15); color: var(--accent-orange);"><i class="fa-solid fa-user-clock"></i></div>
                        <div>
                            <div class="metric-label">Awaiting Customer</div>
                            <div id="metric-orders-awaiting" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(139, 92, 246, 0.15); color: var(--accent-purple);"><i class="fa-solid fa-circle-check"></i></div>
                        <div>
                            <div class="metric-label">Confirmed</div>
                            <div id="metric-orders-confirmed" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(16, 185, 129, 0.15); color: var(--accent-green);"><i class="fa-solid fa-truck"></i></div>
                        <div>
                            <div class="metric-label">Delivered</div>
                            <div id="metric-orders-delivered" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(16, 185, 129, 0.15); color: var(--accent-green);"><i class="fa-solid fa-indian-rupee-sign"></i></div>
                        <div>
                            <div class="metric-label">Total Revenue</div>
                            <div id="metric-revenue" class="metric-value">₹0.00</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(6, 182, 212, 0.15); color: var(--accent-cyan);"><i class="fa-solid fa-wallet"></i></div>
                        <div>
                            <div class="metric-label">Total Profit</div>
                            <div id="metric-profit" class="metric-value">₹0.00</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(249, 115, 22, 0.15); color: var(--accent-orange);"><i class="fa-solid fa-piggy-bank"></i></div>
                        <div>
                            <div class="metric-label">Savings Delivered</div>
                            <div id="metric-savings" class="metric-value">₹0.00</div>
                        </div>
                    </div>
                `;
        } else {
          metricsContainer.innerHTML = `
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(59, 130, 246, 0.15); color: var(--primary);"><i class="fa-solid fa-cart-shopping"></i></div>
                        <div>
                            <div class="metric-label">Active Tickets</div>
                            <div id="metric-active-tickets" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(16, 185, 129, 0.15); color: var(--accent-green);"><i class="fa-solid fa-clipboard-check"></i></div>
                        <div>
                            <div class="metric-label">Claimed Tickets</div>
                            <div id="metric-claimed-tickets" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(249, 115, 22, 0.15); color: var(--accent-orange);"><i class="fa-solid fa-hourglass-half"></i></div>
                        <div>
                            <div class="metric-label">Pending Tickets</div>
                            <div id="metric-pending-tickets" class="metric-value">0</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(139, 92, 246, 0.15); color: var(--accent-purple);"><i class="fa-solid fa-stopwatch"></i></div>
                        <div>
                            <div class="metric-label">Avg Response Time</div>
                            <div id="metric-response-time" class="metric-value">0s</div>
                        </div>
                    </div>
                    <div class="metric-card glass-panel">
                        <div class="metric-icon" style="background-color: rgba(6, 182, 212, 0.15); color: var(--accent-cyan);"><i class="fa-solid fa-chart-line"></i></div>
                        <div>
                            <div class="metric-label">Orders Today</div>
                            <div id="metric-orders-today-mod" class="metric-value">0</div>
                        </div>
                    </div>
                `;
        }
      }

      async function loadMetrics() {
        try {
          const m = await apiRequest("/api/admin/dashboard/metrics");

          if (currentUser.role === "ADMIN") {
            // Update original metric elements (if they exist)
            const elOrdersToday = document.getElementById(
              "metric-orders-today",
            );
            if (elOrdersToday) elOrdersToday.innerText = m.orders_today;

            const elRevenue = document.getElementById("metric-revenue");
            if (elRevenue)
              elRevenue.innerText = `₹${parseFloat(m.revenue).toFixed(2)}`;

            const elProfit = document.getElementById("metric-profit");
            if (elProfit)
              elProfit.innerText = `₹${parseFloat(m.profit).toFixed(2)}`;

            const elSavings = document.getElementById("metric-savings");
            if (elSavings)
              elSavings.innerText = `₹${parseFloat(m.total_savings_delivered).toFixed(2)}`;

            // Update Analytics section metrics
            const elAnalyticsOrdersToday = document.getElementById(
              "metric-orders-today-analytics",
            );
            if (elAnalyticsOrdersToday) elAnalyticsOrdersToday.innerText = m.orders_today;

            const elAnalyticsRevenue = document.getElementById("metric-revenue-analytics");
            if (elAnalyticsRevenue)
              elAnalyticsRevenue.innerText = `₹${parseFloat(m.revenue).toFixed(2)}`;

            const elAnalyticsProfit = document.getElementById("metric-profit-analytics");
            if (elAnalyticsProfit)
              elAnalyticsProfit.innerText = `₹${parseFloat(m.profit).toFixed(2)}`;

            const elAnalyticsSavings = document.getElementById("metric-savings-analytics");
            if (elAnalyticsSavings)
              elAnalyticsSavings.innerText = `₹${parseFloat(m.total_savings_delivered).toFixed(2)}`;

            const elAnalyticsCustomers = document.getElementById("metric-customers-analytics");
            if (elAnalyticsCustomers) elAnalyticsCustomers.innerText = m.total_customers;

            const elAnalyticsPending = document.getElementById("metric-orders-pending-analytics");
            if (elAnalyticsPending) elAnalyticsPending.innerText = m.orders_pending_review;

            const elAnalyticsAwaiting = document.getElementById(
              "metric-orders-awaiting-analytics",
            );
            if (elAnalyticsAwaiting) elAnalyticsAwaiting.innerText = m.orders_awaiting_customer;

            const elAnalyticsConfirmed = document.getElementById(
              "metric-orders-confirmed-analytics",
            );
            if (elAnalyticsConfirmed) elAnalyticsConfirmed.innerText = m.orders_confirmed;
          } else {
            const elActive = document.getElementById("metric-active-tickets");
            if (elActive) elActive.innerText = m.active_tickets;

            const elClaimed = document.getElementById("metric-claimed-tickets");
            if (elClaimed) elClaimed.innerText = m.claimed_tickets;

            const elPending = document.getElementById("metric-pending-tickets");
            if (elPending) elPending.innerText = m.pending_tickets;

            const elResponse = document.getElementById("metric-response-time");
            if (elResponse) {
              const seconds = Math.round(m.avg_response_time);
              if (seconds < 60) {
                elResponse.innerText = `${seconds}s`;
              } else {
                const mins = Math.floor(seconds / 60);
                const secs = seconds % 60;
                elResponse.innerText = `${mins}m ${secs}s`;
              }
            }

            const elOrdersTodayMod = document.getElementById(
              "metric-orders-today-mod",
            );
            if (elOrdersTodayMod) elOrdersTodayMod.innerText = m.orders_today;
          }
        } catch (e) {
          console.log("Error loading dashboard metrics:", e);
        }
      }

      window.loadQueue = async function () {
        const filter = document.getElementById("queue-filter").value;
        try {
          const queue = await apiRequest(
            `/api/moderator/queue${filter ? "?status_filter=" + filter : ""}`,
          );
          activeOrders = queue;
          renderQueue();
        } catch (e) {
          console.log("Error loading queue:", e);
        }
      };

      function renderQueue() {
        const container = document.getElementById("queue-list");
        container.innerHTML = "";

        const countBadge = document.getElementById("queue-tab-count");
        if (countBadge) {
          countBadge.innerText = activeOrders.length;
          countBadge.style.display = activeOrders.length > 0 ? "inline-block" : "none";
        }

        if (activeOrders.length === 0) {
          container.innerHTML = `<p style="color: var(--text-muted); font-size: 12px; text-align: center; padding: 24px;">No active requests in queue.</p>`;
          return;
        }

        activeOrders.forEach((order) => {
          const card = document.createElement("div");
          card.className =
            "queue-card" +
            (selectedOrder && selectedOrder.order_id === order.order_id
              ? " selected"
              : "");
          card.dataset.status = order.status;

          // Extract assigned label
          let assignLabel = "Unassigned";
          let assignColor = "var(--text-muted)";
          if (order.assigned_moderator_id) {
            if (order.assigned_moderator_id === currentUser.id) {
              assignLabel = "● Assigned to You";
              assignColor = "var(--accent-green)";
            } else {
              assignLabel = "● Assigned to Other";
              assignColor = "var(--accent-orange)";
            }
          }

          const timeAgo = order.created_at ? timeSince(order.created_at) : "";

          card.innerHTML = `
                    <div class="queue-header">
                        <span style="font-family: monospace; font-size: 11px; font-weight: 600; color: var(--text-muted);">#${order.order_id.slice(0, 8)}</span>
                        <span class="badge ${order.status}">${order.status.replace(/_/g, " ")}</span>
                    </div>
                    <div style="font-size: 13px; font-weight: 600; margin-bottom: 3px;">${order.customer_name || order.customer_phone}</div>
                    <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px; display: flex; gap: 8px;">
                        <span><i class="fa-solid fa-location-dot" style="font-size: 9px;"></i> ${order.delivery_city}</span>
                        ${timeAgo ? `<span><i class="fa-regular fa-clock" style="font-size: 9px;"></i> ${timeAgo}</span>` : ""}
                    </div>
                    <div style="font-size: 10px; font-weight: 700; color: ${assignColor};">${assignLabel}</div>
                `;

          card.onclick = () => selectTicket(order);
          container.appendChild(card);
        });
      }

      async function selectTicket(order) {
        selectedOrder = order;
        renderQueue();

        // Set chat header + enable composer
        document.getElementById("chat-header-title").innerText =
          `Chat: ${order.customer_phone}`;
        document.getElementById("composer-text").disabled = false;
        document.getElementById("btn-send-message").disabled = false;
        await pollChat();

        renderTicketDetails();
        switchOrdersTab('ticket');
      }

      async function pollChat() {
        if (!selectedOrder) return;
        // Moderators have no chat access — only admins monitor chat
        if (currentUser.role !== "ADMIN") return;
        try {
          const messages = await apiRequest(
            `/api/chat/${selectedOrder.customer_id}/messages`,
          );
          renderMessages(messages);
        } catch (e) {
          console.log("Error loading chat messages:", e);
        }
      }

      function renderMessages(msgs) {
        const chat = document.getElementById("chat-messages");
        chat.innerHTML = "";

        if (msgs.length === 0) {
          chat.innerHTML = `<div class="chat-bubble system">No chat activity logs found.</div>`;
          return;
        }

        msgs.forEach((m) => {
          const bubble = document.createElement("div");
          let senderClass = "system";
          let senderName = "System";

          if (m.sender_role === "CUSTOMER") {
            senderClass = "customer";
            senderName = "Customer";
          } else if (
            m.sender_role === "MODERATOR" ||
            m.sender_role === "ADMIN"
          ) {
            senderClass = "moderator";
            senderName = m.sender_role === "ADMIN" ? "Admin" : "Moderator";
          }

          bubble.className = `chat-bubble ${senderClass}`;
          bubble.innerHTML = `
                    <div class="chat-sender">${senderName}</div>
                    <div style="white-space: pre-wrap;">${m.message}</div>
                    <div class="chat-timestamp">${new Date(m.created_at + "Z").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</div>
                `;
          chat.appendChild(bubble);
        });

        chat.scrollTop = chat.scrollHeight;
      }

      window.sendMessage = async function () {
        const txt = document.getElementById("composer-text").value.trim();
        if (!txt || !selectedOrder) return;

        document.getElementById("composer-text").value = "";
        try {
          await apiRequest(
            `/api/chat/${selectedOrder.user_id}/send`,
            "POST",
            { message: txt, order_id: selectedOrder.id },
          );
          await pollChat();
        } catch (err) {
          console.log("Failed to send message:", err.message);
        }
      };

      // Handle enter key press
      document
        .getElementById("composer-text")
        .addEventListener("keypress", (e) => {
          if (e.key === "Enter") sendMessage();
        });

      function renderTicketDetails() {
        const placeholder = document.getElementById(
          "ticket-unselected-placeholder",
        );
        const panel = document.getElementById("ticket-detail-panel");

        if (!selectedOrder) {
          placeholder.style.display = "block";
          panel.style.display = "none";
          return;
        }

        currentQuotePreview = null;
        const qpBlock = document.getElementById("quote-preview-block");
        if(qpBlock) qpBlock.style.display = "none";
        const btnPreview = document.getElementById("btn-preview-quote");
        if(btnPreview) btnPreview.style.display = "block";

        placeholder.style.display = "none";
        panel.style.display = "flex";

        const isClaimedByMe =
          selectedOrder.assigned_moderator_id === currentUser.id;
        const isAdmin = currentUser.role === "ADMIN";

        // 1. Claim Ticket Block
        const claimBlock = document.getElementById("claim-block");
        if (!selectedOrder.assigned_moderator_id) {
          claimBlock.style.display = "block";
        } else {
          claimBlock.style.display = "none";
        }

        // 2. Per-product Price Entry Block
        const pricesBlock = document.getElementById("prices-block");
        const editablePrices = [
          "pending_review",
          "reviewing"
        ].includes(selectedOrder.status);
        if (editablePrices && (isClaimedByMe || isAdmin)) {
          pricesBlock.style.display = "block";
          renderPriceRows();
        } else {
          pricesBlock.style.display = "none";
        }

        // 2.5 Awaiting Customer Block
        const awaitCustBlock = document.getElementById("awaiting-customer-block");
        if (selectedOrder.status === "awaiting_customer") {
          awaitCustBlock.style.display = "block";
        } else {
          awaitCustBlock.style.display = "none";
        }

        // 3. Verify Payment & Place Order Block
        const placeBlock = document.getElementById("place-block");
        if (selectedOrder.status === "awaiting_payment") {
          placeBlock.style.display = "block";
        } else {
          placeBlock.style.display = "none";
        }
        // 4. Mark Delivered Block (Admin only — moderators only price)
        const deliverBlock = document.getElementById("deliver-block");
        if (selectedOrder.status === "placed" && isAdmin) {
          deliverBlock.style.display = "block";
        } else {
          deliverBlock.style.display = "none";
        }

        // 5. Cancel Block (Admin only — any active order)
        const cancelBlock = document.getElementById("cancel-block");
        const cancellable = !["delivered", "completed", "cancelled"].includes(
          selectedOrder.status,
        );
        cancelBlock.style.display = isAdmin && cancellable ? "block" : "none";
      }

      const KNOWN_STORES = [
        "zepto",
        "blinkit",
        "instamart",
        "bigbasket",
        "jiomart",
      ];

      function renderPriceRows() {
        const list = document.getElementById("prices-list");
        list.innerHTML = "";
        const items = selectedOrder.items || [];
        if (!items.length) {
          list.innerHTML = `<p style="font-size:12px;color:var(--text-muted);">This order has no line items.</p>`;
          return;
        }
        const storeOptions = KNOWN_STORES.map(
          (s) =>
            `<option value="${s}">${s.charAt(0).toUpperCase() + s.slice(1)}</option>`,
        ).join("");
        items.forEach((it, idx) => {
          const row = document.createElement("div");
          row.className = "price-item-row";
          row.style.cssText =
            "border:1px solid var(--border); border-radius:10px; padding:10px; background:rgba(15,23,42,0.4);";
          row.innerHTML = `
            <div style="font-size:13px; font-weight:600; margin-bottom:8px;">${it.quantity}× ${it.name}</div>
            <div style="display:flex; gap:8px;">
              <input type="number" class="input-control pi-price" data-item-id="${it.id}" min="0" step="0.01"
                placeholder="Unit ₹" value="${it.unit_price != null ? it.unit_price : ""}" style="flex:1; padding:8px 10px; font-size:12px;" />
              <select class="input-control pi-store" data-item-id="${it.id}" style="width:120px; padding:8px 10px; font-size:12px;">
                <option value="">Store…</option>
                ${storeOptions}
              </select>
            </div>`;
          list.appendChild(row);
          if (it.store) {
            const sel = row.querySelector(".pi-store");
            sel.value = KNOWN_STORES.includes(it.store) ? it.store : "";
          }
          row
            .querySelector(".pi-price")
            .addEventListener("input", updatePriceSubtotal);
        });
        updatePriceSubtotal();
      }

      function updatePriceSubtotal() {
        let subtotal = 0;
        (selectedOrder.items || []).forEach((it) => {
          const inp = document.querySelector(`.pi-price[data-item-id="${it.id}"]`);
          const val = inp ? parseFloat(inp.value) : NaN;
          if (!isNaN(val)) subtotal += val * it.quantity;
        });
        document.getElementById("prices-subtotal").innerText =
          `Subtotal: ₹${subtotal.toFixed(2)}`;
      }

      window.claimOrder = async function () {
        if (!selectedOrder) return;
        setLoading("btn-claim-order", true);
        try {
          const res = await apiRequest(
            `/api/moderator/orders/${selectedOrder.order_id}/claim`,
            "PUT",
          );

          // Update selected order assignment state
          selectedOrder.status = res.status;
          selectedOrder.assigned_moderator_id = res.assigned_moderator_id;

          await loadQueue();
          renderTicketDetails();
          await pollChat();
        } catch (err) {
          alert("Claim ticket failed: " + err.message);
        } finally {
          setLoading("btn-claim-order", false);
        }
      };

      let currentQuotePreview = null;

      window.previewQuote = async function() {
        if (!selectedOrder) return;
        const items = [];
        let missing = false;
        (selectedOrder.items || []).forEach((it) => {
          const priceEl = document.querySelector(`.pi-price[data-item-id="${it.id}"]`);
          const storeEl = document.querySelector(`.pi-store[data-item-id="${it.id}"]`);
          const price = priceEl ? parseFloat(priceEl.value) : NaN;
          const store = storeEl ? storeEl.value : "";
          if (isNaN(price) || !store) { missing = true; return; }
          items.push({ item_id: it.id, name: it.name, unit_price: price, store: store });
        });

        if (missing || items.length === 0) {
          alert("Please enter a total cost and store for every line item.");
          return;
        }

        setLoading("btn-preview-quote", true);
        try {
          const res = await apiRequest(`/api/moderator/orders/${selectedOrder.order_id}/preview-quote`, "POST", { items: items });
          currentQuotePreview = res;
          
          document.getElementById("quote-preview-block").style.display = "block";
          document.getElementById("btn-preview-quote").style.display = "none";
          
          // Setup fields
          document.getElementById("quote-delivery-fee").value = res.delivery_fee;
          document.getElementById("quote-store-discount").value = res.store_discount;
          document.getElementById("quote-snapsave-discount").value = res.snapsave_discount;
          document.getElementById("quote-profit").value = res.profit;

          const warnEl = document.getElementById("delivery-fee-warning");
          if (res.delivery_fee > 0) {
            warnEl.style.display = "inline";
          } else {
            warnEl.style.display = "none";
          }

          recalculatePreviewTotal();
        } catch (err) {
          alert("Preview failed: " + err.message);
        }
        setLoading("btn-preview-quote", false);
      };

      window.recalculatePreviewTotal = function() {
        if (!currentQuotePreview) return;
        const deliveryFee = parseFloat(document.getElementById("quote-delivery-fee").value) || 0;
        const storeDiscount = parseFloat(document.getElementById("quote-store-discount").value) || 0;
        const snapDiscount = parseFloat(document.getElementById("quote-snapsave-discount").value) || 0;
        const profit = parseFloat(document.getElementById("quote-profit").value) || 0;
        
        currentQuotePreview.delivery_fee = deliveryFee;
        currentQuotePreview.store_discount = storeDiscount;
        currentQuotePreview.snapsave_discount = snapDiscount;
        currentQuotePreview.profit = profit;
        
        const finalPrice = currentQuotePreview.subtotal + currentQuotePreview.platform_fee + deliveryFee + profit - storeDiscount - snapDiscount;
        currentQuotePreview.final_price = finalPrice;
        
        document.getElementById("preview-subtotal").innerText = `₹${currentQuotePreview.subtotal.toFixed(2)}`;
        document.getElementById("preview-platform").innerText = `₹${currentQuotePreview.platform_fee.toFixed(2)}`;
        document.getElementById("preview-final").innerText = `₹${finalPrice.toFixed(2)}`;
      };

      window.submitPrices = async function () {
        if (!selectedOrder || !currentQuotePreview) return;

        setLoading("btn-submit-prices", true);
        try {
          const res = await apiRequest(
            `/api/moderator/orders/${selectedOrder.order_id}/price`,
            "POST",
            currentQuotePreview,
          );

          selectedOrder.status = res.status;
          selectedOrder.items = res.items || selectedOrder.items;
          await loadQueue();
          renderTicketDetails();
          if (currentUser.role === "ADMIN") await pollChat();
        } catch (err) {
          alert("Failed to submit quote: " + err.message);
        } finally {
          setLoading("btn-submit-prices", false);
        }
      };

      window.placeOrderWithEta = async function () {
        if (!selectedOrder) return;

        const eta = prompt("Enter the time till delivery in minutes (e.g. 45):", "45");
        if (eta === null) {
          // User clicked cancel
          return;
        }
        
        if (!eta.trim() || isNaN(parseInt(eta, 10))) {
          alert("Please enter a valid number of minutes.");
          return;
        }

        setLoading("btn-place-order", true);
        try {
          const res = await apiRequest(
            `/api/moderator/orders/${selectedOrder.order_id}/place`,
            "POST",
            {
              eta_mins: parseInt(eta, 10)
            },
          );

          selectedOrder.status = res.status;
          await loadQueue();
          renderTicketDetails();
          await pollChat();
        } catch (err) {
          alert("Placement failure: " + err.message);
        } finally {
          setLoading("btn-place-order", false);
        }
      };

      window.deliverOrder = async function () {
        if (!selectedOrder) return;
        setLoading("btn-deliver-order", true);
        try {
          const res = await apiRequest(
            `/api/moderator/orders/${selectedOrder.order_id}/deliver`,
            "PUT",
          );

          selectedOrder.status = res.status;
          await loadQueue();
          renderTicketDetails();
          await pollChat();
        } catch (err) {
          alert("Delivery completion failure: " + err.message);
        } finally {
          setLoading("btn-deliver-order", false);
        }
      };

      // API Fetch Wrapper
      async function apiRequest(endpoint, method = "GET", body = null) {
        const headers = { "Content-Type": "application/json" };
        if (idToken) {
          headers["Authorization"] = `Bearer ${idToken}`;
        }

        const options = { method, headers };
        if (body) {
          options.body = JSON.stringify(body);
        }

        const res = await fetch(`${API_BASE}${endpoint}`, options);
        if (!res.ok) {
          const errorData = await res
            .json()
            .catch(() => ({ detail: "Unknown server error" }));
          throw new Error(
            errorData.detail || `HTTP error! status: ${res.status}`,
          );
        }
        return await res.json();
      }

      function showAuthAlert(msg, type) {
        const container = document.getElementById("auth-alert-container");
        container.innerHTML = msg
          ? `<div class="alert alert-${type}"><i class="fa-solid ${type === "error" ? "fa-circle-exclamation" : "fa-circle-check"}"></i> ${msg}</div>`
          : "";
      }

      function timeSince(dateStr) {
        const now = new Date();
        const past = new Date(dateStr);
        const diffMs = now - past;
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) return "just now";
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHrs = Math.floor(diffMins / 60);
        if (diffHrs < 24) return `${diffHrs}h ago`;
        return `${Math.floor(diffHrs / 24)}d ago`;
      }

      function setLoading(btnId, isLoading) {
        const btn = document.getElementById(btnId);
        if (!btn) return;
        if (isLoading) {
          btn.disabled = true;
          btn.dataset.originalHTML = btn.innerHTML;
          btn.innerHTML = `<span class="loading-spinner"></span> Loading...`;
        } else {
          btn.disabled = false;
          if (btn.dataset.originalHTML) {
            btn.innerHTML = btn.dataset.originalHTML;
          }
        }
      }

      let betaMetricsInterval = null;

      window.toggleBetaView = function () {
        document.getElementById("dashboard-metrics").style.display = "none";
        document.getElementById("dashboard-main").style.display = "none";
        document
          .querySelectorAll(".admin-nav-item")
          .forEach((b) =>
            b.classList.toggle("active", b.dataset.section === "beta"),
          );

        const betaView = document.getElementById("beta-program-view");
        betaView.style.display = "flex";

        loadBetaDashboard();
        clearInterval(betaMetricsInterval);
        betaMetricsInterval = setInterval(loadBetaDashboard, 8000);
      };

      window.exitBetaView = function () {
        document.getElementById("beta-program-view").style.display = "none";
        document.getElementById("dashboard-main").style.display = "flex";
        document.getElementById("dashboard-metrics").style.display = "flex";
        clearInterval(betaMetricsInterval);
        if (currentUser && currentUser.role === "ADMIN") {
          showAdminSection("tickets");
        }
      };

      async function loadBetaDashboard() {
        try {
          // 1. Load Metrics
          const m = await apiRequest("/api/admin/dashboard/beta-metrics");
          document.getElementById("beta-metric-users").innerText =
            m.total_beta_users;
          document.getElementById("beta-metric-submitted").innerText =
            m.orders_submitted;
          document.getElementById("beta-metric-completed").innerText =
            m.orders_completed;
          document.getElementById("beta-metric-mods").innerText =
            m.active_moderators;

          // Format Avg Moderator Response Time
          const respSecs = Math.round(m.avg_first_response_time);
          document.getElementById("beta-metric-response-time").innerText =
            formatSeconds(respSecs);

          // Format Avg Confirmation Time
          const confSecs = Math.round(m.avg_confirm_time);
          document.getElementById("beta-metric-confirm-time").innerText =
            formatSeconds(confSecs);

          document.getElementById("beta-metric-avg-profit").innerText =
            `₹${parseFloat(m.avg_profit_per_order).toFixed(2)}`;
          document.getElementById("beta-metric-avg-savings").innerText =
            `₹${parseFloat(m.avg_savings_delivered).toFixed(2)}`;

          // 2. Load Incidents Logs
          const incidents = await apiRequest("/api/admin/incidents");
          renderBetaIncidents(incidents);

          // 3. Load Feedback Logs (Admin Only)
          if (currentUser.role === "ADMIN") {
            const feedback = await apiRequest("/api/admin/feedback");
            renderBetaFeedback(feedback);
          } else {
            document.getElementById("feedback-list").innerHTML = `
                        <div class="alert alert-error">
                            <i class="fa-solid fa-lock"></i> Admin privileges required to view customer feedback logs.
                        </div>
                    `;
          }
        } catch (e) {
          console.log("Error loading beta dashboard data:", e);
        }
      }

      function formatSeconds(totalSec) {
        if (totalSec < 60) return `${totalSec}s`;
        const mins = Math.floor(totalSec / 60);
        const secs = totalSec % 60;
        return `${mins}m ${secs}s`;
      }

      function renderBetaIncidents(incidents) {
        const container = document.getElementById("incidents-list");
        container.innerHTML = "";
        if (incidents.length === 0) {
          container.innerHTML = `<p style="font-size: 11px; color: var(--text-muted); text-align: center; padding: 10px;">No incidents logged yet.</p>`;
          return;
        }
        incidents.forEach((inc) => {
          const item = document.createElement("div");
          item.className = "address-card";
          item.style.padding = "10px";
          item.style.marginBottom = "6px";
          item.style.backgroundColor = "rgba(239, 68, 68, 0.05)";
          item.style.borderColor = "rgba(239, 68, 68, 0.2)";

          item.innerHTML = `
                    <div style="display: flex; justify-content: space-between; font-size: 11px; margin-bottom: 4px;">
                        <span style="font-weight: bold; color: var(--accent-orange);">${inc.incident_type}</span>
                        <span style="color: var(--text-muted);">${new Date(inc.created_at + "Z").toLocaleTimeString()}</span>
                    </div>
                    <div style="font-size: 12px; white-space: pre-wrap; margin-bottom: 4px;">${inc.notes || "No details."}</div>
                    <div style="font-size: 10px; color: var(--text-muted);">
                        <span>Mod: ${inc.moderator_phone}</span>
                        ${inc.order_id ? ` | <span style="font-family: monospace;">Order: #${inc.order_id.slice(0, 8)}</span>` : ""}
                    </div>
                `;
          container.appendChild(item);
        });
      }

      function renderBetaFeedback(feedback) {
        const container = document.getElementById("feedback-list");
        container.innerHTML = "";
        if (feedback.length === 0) {
          container.innerHTML = `<p style="font-size: 11px; color: var(--text-muted); text-align: center; padding: 10px;">No feedback received yet.</p>`;
          return;
        }
        feedback.forEach((f) => {
          const item = document.createElement("div");
          item.className = "address-card";
          item.style.padding = "12px";
          item.style.style = "margin-bottom: 8px;";
          item.style.backgroundColor = "rgba(16, 185, 129, 0.03)";

          let stars = "";
          for (let i = 1; i <= 5; i++) {
            stars += `<i class="fa-star ${i <= f.rating ? "fa-solid" : "fa-regular"}" style="color: #fbbf24; font-size: 11px; margin-right: 2px;"></i>`;
          }

          item.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div>${stars}</div>
                        <span style="font-size: 10px; color: var(--text-muted);">${new Date(f.created_at + "Z").toLocaleDateString()}</span>
                    </div>
                    <div style="font-size: 12px; margin-bottom: 6px; display: flex; flex-direction: column; gap: 4px;">
                        <div><strong style="color: var(--accent-green);">Went Well:</strong> ${f.what_went_well || "N/A"}</div>
                        <div><strong style="color: var(--accent-orange);">Confusing:</strong> ${f.what_was_confusing || "N/A"}</div>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 10px; border-top: 1px solid var(--border); padding-top: 6px; color: var(--text-muted);">
                        <span>Use again: <strong style="color: ${f.would_use_again ? "var(--accent-green)" : "red"};">${f.would_use_again ? "YES" : "NO"}</strong></span>
                        <span>Cust: ${f.customer_phone}</span>
                    </div>
                `;
          container.appendChild(item);
        });
      }

      window.submitIncident = async function () {
        const orderId = document.getElementById("inc-order-id").value.trim();
        const type = document.getElementById("inc-type").value;
        const notes = document.getElementById("inc-notes").value.trim();

        if (!notes) {
          alert("Please add notes describing the incident.");
          return;
        }

        setLoading("btn-log-incident", true);
        try {
          await apiRequest("/api/moderator/incidents", "POST", {
            order_id: orderId || null,
            incident_type: type,
            notes: notes,
          });
          document.getElementById("inc-order-id").value = "";
          document.getElementById("inc-notes").value = "";
          await loadBetaDashboard();
        } catch (err) {
          alert("Incident logging failed: " + err.message);
        } finally {
          setLoading("btn-log-incident", false);
        }
      };

      window.switchOrdersTab = function(tabName) {
        const ws = document.getElementById("workspace-container");
        const tabs = document.querySelectorAll(".orders-tab");
        
        tabs.forEach(t => t.classList.remove("active"));
        if (tabName === 'queue') {
          ws.className = "view-queue";
          document.querySelector('.orders-tab[data-tab="queue"]').classList.add("active");
        } else {
          ws.className = "view-ticket";
          document.querySelector('.orders-tab[data-tab="ticket"]').classList.add("active");
        }
      };

      window.switchTab = function (tabName) {
        const buttons = document.querySelectorAll(".mobile-tab-btn");
        buttons.forEach((btn) => btn.classList.remove("active"));

        if (tabName === "queue") buttons[0].classList.add("active");
        if (tabName === "chat") buttons[1].classList.add("active");
        if (tabName === "ticket") buttons[2].classList.add("active");
        if (tabName === "admin") buttons[3].classList.add("active");

        const adminPanel = document.getElementById("panel-admin");
        const queuePanel = document.getElementById("panel-queue");
        const chatPanel = document.getElementById("panel-chat");
        const ticketPanel = document.getElementById("panel-ticket");

        if (adminPanel) adminPanel.classList.remove("mobile-show");
        if (queuePanel) queuePanel.classList.remove("mobile-show");
        if (chatPanel) chatPanel.classList.remove("mobile-show");
        if (ticketPanel) ticketPanel.classList.remove("mobile-show");

        if (tabName === "admin" && adminPanel) {
          adminPanel.classList.add("mobile-show");
        } else if (tabName === "chat" && chatPanel) {
          chatPanel.classList.add("mobile-show");
        } else if (tabName === "ticket" && ticketPanel) {
          ticketPanel.classList.add("mobile-show");
        } else if (tabName === "queue" && queuePanel) {
          queuePanel.classList.add("mobile-show");
        }
      };

      // ── Session Restore on page load ──
      (async function restoreSession() {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (!saved) return;
        idToken = saved;
        try {
          await checkUserSession();
        } catch (e) {
          // Token expired or invalid — clear it and show login
          localStorage.removeItem(STORAGE_KEY);
          idToken = null;
          showLoggedOutView();
        }
      })();
    
