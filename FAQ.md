### **1\. How long/large will the input documents typically be? A single chapter or paper, or could it be a full textbook?**

The primary input will typically be a **single chapter or topic**, with **NCERT textbook chapters (Classes 6–12)** serving as the reference standard. However, the system should not be tightly coupled to NCERT and should be capable of handling documents of varying lengths and complexity.

The output should be **adaptive to the topic being taught**, rather than following a fixed template. The pedagogical depth, explanations, examples, and activities should be tuned according to the grade level, subject, and complexity of the input content.

---

### **2\. Do you have 2–3 sample documents I can test with, ideally from different subjects (e.g., one STEM, one humanities)?**

For initial development and testing, you can use **NCERT textbook chapters** as representative input documents. They provide a diverse set of topics across Science, Mathematics, Social Science, and Languages, making them a good benchmark for validating the pipeline across different domains.

---

### **3\. Is the "5 periods × 40 minutes" split fixed, or should the system decide the number and length of periods based on the content?**

The lesson structure **should be flexible**.

Rather than assuming a fixed number of periods, the system should determine an appropriate instructional plan based on factors such as:

* Content volume  
* Conceptual complexity  
* Learning objectives  
* Target grade level  
* Recommended pacing

The generated teaching plan should adapt naturally to the material instead of forcing it into predefined time slots.

---

### **4\. What should count as a "hallucination" for validation—content not backed by the extracted knowledge or content not backed by the original document?**

The system should remain **grounded in the primary source** for all factual and conceptual content.

Additional knowledge from **secondary sources** may be used **only to improve pedagogy**, such as:

* Teaching strategies  
* Analogies  
* Classroom activities  
* Assessment approaches  
* Learning science best practices

However, these secondary sources **must not introduce new subject matter, facts, or concepts that extend beyond the scope of the primary source** without clearly distinguishing them. Validation should therefore ensure that the instructional content remains faithful to the knowledge contained in the primary reference.

---

### **5\. Do you expect a single-stage AI call/prompt or a properly separated multi-stage pipeline with distinct steps?**

We expect you to design the architecture that produces the best possible user experience and output quality.

A **multi-stage pipeline** is likely to be more robust, but the exact implementation is left to your judgment. From the user's perspective, the interaction should feel simple and seamless.

At the beginning of the workflow, the system may ask a small number of **clarifying questions**, if needed, to understand aspects such as:

* Target audience or grade  
* Teaching objectives  
* Desired teaching style  
* Time constraints  
* Any other information that materially improves the generated lesson plan

After collecting the necessary context, the pipeline should autonomously orchestrate the remaining stages to produce a high-quality, grounded, and pedagogically effective output.

---

### **6\. Are there any API requirements or restrictions for this project? Do I need to use a specific provider or purchase API credits?**

There are **no mandatory API or model requirements** for this project. You are free to choose the models, providers, and overall AI stack that you believe will produce the best results.

For development, you may:

* Use **free APIs or open-source models** where appropriate.  
* Explore platforms such as **OpenRouter**, which provides access to multiple models, including several free options suitable for experimentation and prototyping.  
* If your chosen approach benefits from more capable models, you may optionally spend a small amount on API credits (e.g., a few dollars) to access higher-quality models.

The focus of the project is **the quality of the solution, system design, grounding, and user experience**, not the specific AI provider you choose. We encourage you to select models and APIs based on the requirements of each stage of your pipeline, balancing capability, cost, latency, and reliability.

---

### **7\. To optimize document parsing costs, can we ask users to classify their uploaded documents before processing?**

Yes, that is a good approach, and we encourage cost-aware routing wherever it does not significantly impact the user experience.

In our use case, the primary inputs will **generally be PDF versions of NCERT textbook chapters (Classes 6–12)** or documents of a similar nature. **You can treat NCERT textbooks as the benchmark** while designing the parsing pipeline. These documents are predominantly text-based but often contain **images, diagrams, figures, tables, maps, and mathematical equations**, depending on the subject and grade level.

A lightweight clarification step at the beginning of the workflow is perfectly acceptable. For example, users can indicate the nature of the document, such as:

* **Mostly Text**  
* **Text with Tables**  
* **Text with Diagrams/Figures**  
* **Text with Equations**  
* **Scanned PDF**  
* **I'm Not Sure** (let the system decide)

Based on this input, the system can intelligently route the document to the most appropriate parsing strategy. For example:

* **Mostly text documents** → Lightweight or zero-cost parser.  
* **Structured text-heavy documents** → Faster, cost-effective parsing.  
* **Documents with diagrams, images, equations, or complex layouts** → More advanced parsing pipelines only when necessary.

You are also welcome to combine this user input with **automatic heuristics**, such as file type, page count, embedded images, OCR detection, or an initial document inspection, to make better routing decisions.

The exact routing logic, parser selection, and optimization strategy are left to your discretion. We encourage designing a pipeline that balances **accuracy, robustness, latency, and cost**, while keeping the overall user experience simple and seamless.  
