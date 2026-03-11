import streamlit as st
import uuid
import requests
import json
from datetime import datetime

# Use the URL of your Cloud Run service
AGENT_URL = f"https://adk-default-service-name-188869078388.us-central1.run.app"

# --- 1. SET UP PAGE CONFIGURATION ---
st.set_page_config(page_title="Prompt Writer Agent", layout="wide")

# --- 2. SESSION MANAGEMENT (MULTI-CONVERSATION) ---
# Ensure a current session id exists (used for the backend as well)
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    requests.post(
        f"{AGENT_URL}/apps/prompt_specialist/users/bhakris/sessions/{st.session_state.session_id}"
    )

# Hold all conversations in-memory for this user
if "session_histories" not in st.session_state:
    st.session_state.session_histories = {
        st.session_state.session_id: []
    }

if "session_meta" not in st.session_state:
    st.session_state.session_meta = {}

if st.session_state.session_id not in st.session_state.session_meta:
    st.session_state.session_meta[st.session_state.session_id] = {
        "title": "New chat",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

# Convenience alias pointing at the current session's messages
st.session_state.messages = st.session_state.session_histories.setdefault(
    st.session_state.session_id, []
)


def _format_session_label(sid: str) -> str:
    meta = st.session_state.session_meta.get(sid, {})
    title = meta.get("title") or "New chat"
    created_at = meta.get("created_at")
    if created_at:
        return f"{title} – {created_at}"
    return title


# --- 3. SIDEBAR CONTROLS ---
with st.sidebar:
    st.title("Conversation Management")

    # New conversation (creates a brand‑new session)
    if st.button("Start New Session"):
        new_id = str(uuid.uuid4())
        st.session_state.session_id = new_id
        st.session_state.session_histories[new_id] = []
        st.session_state.session_meta[new_id] = {
            "title": "New chat",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        requests.post(
            f"{AGENT_URL}/apps/prompt_specialist/users/bhakris/sessions/{new_id}"
        )
        st.rerun()

    st.divider()

    # Existing conversations: behave like ChatGPT's left‑hand session list
    all_session_ids = list(st.session_state.session_histories.keys())
    if all_session_ids:
        current_index = all_session_ids.index(st.session_state.session_id)
        selected_session_id = st.radio(
            "Your conversations",
            options=all_session_ids,
            format_func=_format_session_label,
            index=current_index,
        )

        if selected_session_id != st.session_state.session_id:
            # Switch to a different stored conversation
            st.session_state.session_id = selected_session_id
            st.session_state.messages = st.session_state.session_histories[
                selected_session_id
            ]
            st.rerun()

# --- 4. BACKEND INTEGRATION ---
def call_google_adk_agent(user_input, session_id):
    target_url = AGENT_URL + "/run"
    
    # 1. Simplify the massive schema to just what is necessary
    payload = {
        "appName": "prompt_specialist",
        "userId": "bhakris",
        "sessionId": str(session_id),
        "newMessage": {
            "role": "user",
            "parts": [
                {
                    "text": user_input  # This is the only part the LLM actually needs
                }
            ]
        },
        "streaming": True
    }

    try:
        # 2. Use json=payload to ensure correct headers
        response = requests.post(target_url, json=payload, timeout=120)
        
        if response.status_code == 200:
            result = response.json()

            # Handle explicit agent errors (e.g., MALFORMED_FUNCTION_CALL)
            if isinstance(result, dict) and "errorCode" in result:
                return f"Agent error ({result.get('errorCode')}): {result.get('errorMessage')}"
            if isinstance(result, list) and result and "errorCode" in result[0]:
                first_err = result[0]
                return f"Agent error ({first_err.get('errorCode')}): {first_err.get('errorMessage')}"

            # Prefer Natasha's functionResponse, if present
            try:
                for item in result:
                    parts = item.get("content", {}).get("parts", [])
                    for part in parts:
                        func_resp = part.get("functionResponse")
                        if func_resp and func_resp.get("name") == "Natasha":
                            return func_resp.get("response", {}).get("result")

                # Fallback: first plain-text model message
                for item in reversed(result):
                    parts = item.get("content", {}).get("parts", [])
                    for part in parts:
                        if "text" in part:
                            return part["text"]

                return f"Unexpected response format: {result}"
            except (KeyError, IndexError, TypeError, AttributeError):
                return f"Unexpected response format: {result}"
            
    except Exception as e:
        return f"Request failed: {str(e)}"

# --- 5. CHAT INTERFACE ---
st.title("Prompt Writer Agent")
st.markdown("I am an agent that helps you craft efficient prompts")

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("How can I help you today?"):
    # If this is the first user turn for this session, use it to name the chat
    meta = st.session_state.session_meta.get(st.session_state.session_id, {})
    if not meta.get("title") or meta.get("title") == "New chat":
        short_title = prompt.strip().split("\n", 1)[0][:60]
        if len(prompt.strip().split("\n", 1)[0]) > 60:
            short_title += "..."
        meta["title"] = short_title or "New chat"
        st.session_state.session_meta[st.session_state.session_id] = meta

    # Display user message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Display assistant response
    with st.chat_message("assistant"):
        with st.spinner("Agent Thinking..."):
            response_text = call_google_adk_agent(prompt, st.session_state.session_id)
            st.markdown(response_text)
    
    st.session_state.messages.append({"role": "assistant", "content": response_text})

# Auto-scroll to the bottom on each rerun so latest response is visible
st.markdown(
    """
    <script>
        window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});
    </script>
    """,
    unsafe_allow_html=True,
)
