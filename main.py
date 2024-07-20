from fastapi import FastAPI, HTTPException, Request, File, UploadFile, Form
from pydantic import BaseModel
from typing import Optional
import uuid
from fastapi.middleware.cors import CORSMiddleware
import logging
import os
from utils import transcribe_audio_from_file, generate_random_string, generate_human_touch, create_agent, satisfaction_check, score_scenario, generate_follow_up, save_conversation_to_file, TRAITS

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = {}

from fastapi.staticfiles import StaticFiles

app.mount("/templates", StaticFiles(directory="templates"), name="templates")


from fastapi.responses import FileResponse

@app.get("/")
async def read_index():
    return FileResponse("templates/interview.html")

class Session:
    def __init__(self, candidate_name):
        self.id = str(uuid.uuid4())
        self.candidate_name = candidate_name
        self.current_trait_index = 0
        self.current_scenario_conversation = []
        self.interview_filename = f"{generate_random_string()}_{candidate_name}_interview.txt"
        self.agents = {
            "question_generation": create_agent("question_generation"),
            "satisfaction_check": create_agent("satisfaction_check"),
            "follow_up": create_agent("follow_up"),
            "scoring": create_agent("scoring")
        }

class QuestionRequest(BaseModel):
    session_id: Optional[str] = None
    candidate_name: Optional[str] = None

def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

@app.get("/test")
async def test_route():
    return {"message": "Test route is working"}

@app.post("/start_interview")
async def start_interview(request: QuestionRequest):
    logger.info(f"Received start_interview request: {request}")
    if request.session_id and request.session_id in sessions:
        session = sessions[request.session_id]
    elif request.candidate_name:
        session = Session(request.candidate_name)
        sessions[session.id] = session
        logger.info(f"New session created with ID: {session.id}")
    else:
        raise HTTPException(status_code=400, detail="Either session_id or candidate_name must be provided")

    trait = TRAITS[session.current_trait_index]
    scenario = trait['scenario']
    question = trait['question']

    human_touch_question = generate_human_touch(
        session.agents["question_generation"],
        session.candidate_name,
        scenario,
        question
    )

    session.current_scenario_conversation = [(scenario, human_touch_question, "")]
    save_conversation_to_file(session.interview_filename, (scenario, human_touch_question, ""))

    return {
        "session_id": session.id,
        "question": human_touch_question
    }

class SubmitResponseBody(BaseModel):
    session_id: str
    response_text: str

@app.post("/submit_response")
async def submit_response(
    session_id: str = Form(...),
    audio_file: UploadFile = File(...),
):
    logger.info(f"Received submit_response request with session_id: '{session_id}'")
    logger.info(f"Audio file: '{audio_file.filename}'")

    try:
        session = get_session(session_id)
    except Exception as e:
        logger.error(f"Error getting session: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error getting session: {str(e)}")
    
    if not audio_file:
        raise HTTPException(status_code=400, detail="Audio file is required")
    
    logger.info("check1")
    file_location = f"temp_{audio_file.filename}"
    try:
        with open(file_location, "wb") as f:
            f.write(await audio_file.read())
        logger.info(f"Audio file saved to: {file_location}")

        response_text = transcribe_audio_from_file(file_location)
        logger.info(f"Transcription result: {response_text}")

        if not response_text:
            raise HTTPException(status_code=400, detail="Transcription failed or response text is missing")

        session.current_scenario_conversation[-1] = (
            session.current_scenario_conversation[-1][0],
            session.current_scenario_conversation[-1][1],
            response_text
        )
        logger.info("check2")
        save_conversation_to_file(session.interview_filename, session.current_scenario_conversation[-1])

        trait = TRAITS[session.current_trait_index]
        status, feedback = satisfaction_check(
            session.agents["satisfaction_check"],
            session.current_scenario_conversation[-1][1],
            response_text,
            trait['trait_name']
        )

        if status == "satisfied":
            score = score_scenario(session.agents["scoring"], session.current_scenario_conversation, trait)
            save_conversation_to_file(session.interview_filename, ("Score", score))
            next_scenario = move_to_next_scenario(session)
            return {
                "session_id": session.id,
                "message": "Moving to next scenario",
                "question": next_scenario.get("question"),
                "score": score
            }
            
        elif status == "insufficient":
            if len(session.current_scenario_conversation) >= 2:
                next_scenario = move_to_next_scenario(session)
                return {
                    "session_id": session.id,
                    "message": "Moving to next scenario due to insufficient response",
                    "question": next_scenario.get("question")
                }
            else:
                follow_up_question = generate_follow_up(
                    session.agents["follow_up"],
                    session.candidate_name,
                    session.current_scenario_conversation,
                    len(session.current_scenario_conversation),
                    insufficient=True
                )
                session.current_scenario_conversation.append(("Follow-Up", len(session.current_scenario_conversation), follow_up_question, ""))
                save_conversation_to_file(session.interview_filename, session.current_scenario_conversation[-1])
                return {
                    "session_id": session.id,
                    "message": "Follow-up question for insufficient response",
                    "question": follow_up_question
                }
        else:  # unsatisfied
            follow_up_question = generate_follow_up(
                session.agents["follow_up"],
                session.candidate_name,
                session.current_scenario_conversation,
                len(session.current_scenario_conversation),
                insufficient=False
            )
            session.current_scenario_conversation.append(("Follow-Up", len(session.current_scenario_conversation), follow_up_question, ""))
            save_conversation_to_file(session.interview_filename, session.current_scenario_conversation[-1])

            if len(session.current_scenario_conversation) >= 3:
                next_scenario = move_to_next_scenario(session)
                return {
                    "session_id": session.id,
                    "message": "Moving to next scenario after follow-up",
                    "question": next_scenario.get("question")
                }

            return {
                "session_id": session.id,
                "message": "Follow-up question for unsatisfactory response",
                "question": follow_up_question
            }

    except Exception as e:
        logger.error(f"Unexpected error occurred: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

    finally:
        if os.path.exists(file_location):
            os.remove(file_location)
        logger.info("check 123")

def move_to_next_scenario(session):
    session.current_trait_index += 1
    session.current_scenario_conversation = []

    if session.current_trait_index >= len(TRAITS):
        del sessions[session.id]
        return {"message": "Interview completed"}

    new_trait = TRAITS[session.current_trait_index]
    new_scenario = new_trait['scenario']
    new_question = new_trait['question']
    new_human_touch_question = generate_human_touch(
        session.agents["question_generation"],
        session.candidate_name,
        new_scenario,
        new_question
    )
    session.current_scenario_conversation = [(new_scenario, new_human_touch_question, "")]
    save_conversation_to_file(session.interview_filename, (new_scenario, new_human_touch_question, ""))
    
    return {"question": new_human_touch_question}

def generate_random_string(length=8):
    import random
    import string
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
