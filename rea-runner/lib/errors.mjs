export class RunnerError extends Error {
  /**
   * @param {string} code      stable machine readable code
   * @param {string} message   short human readable message (no file contents)
   * @param {object} [details] extra structured data
   */
  constructor(code, message, details = {}) {
    super(message);
    this.code = code;
    this.details = details;
  }

  toJSON() {
    return { code: this.code, message: this.message, details: this.details };
  }
}
