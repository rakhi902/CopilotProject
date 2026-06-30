"""Service layer: the application's business logic, free of HTTP concerns.

The work lives here so the routers in ``api`` stay thin and the logic can be
unit-tested directly, without a live HTTP server. The main pieces:

    pdf_parsing    extract clean, plain text from an uploaded PDF resume
    jd_scraping    fetch and clean a job description from a URL
    agents/        the LangGraph pipeline (Fit Analyst, Resume Writer, Cover
                   Letter, Interviewer) and its orchestration
    generation     run the pipeline in the background and persist the result
    export         render the cover letter / resume as downloadable documents
    ats / interview_grading / salary / calendar_export   the extra analysis tools
"""
