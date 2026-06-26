import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

type CognitoJson = Record<string, unknown>;

function first(...values: Array<string | undefined>): string {
  return values.find((value) => value && value.trim())?.trim() ?? "";
}

function authMode(): string {
  return first(process.env.RAKU_AUTH_MODE, process.env.NEXT_PUBLIC_RAKU_AUTH_MODE).toLowerCase();
}

function clientId(): string {
  return first(process.env.COGNITO_CLIENT_ID, process.env.COGNITO_USER_POOL_CLIENT_ID);
}

function region(): string {
  const explicit = first(process.env.AWS_REGION, process.env.AWS_DEFAULT_REGION);
  if (explicit) return explicit;
  const issuer = first(process.env.COGNITO_ISSUER, process.env.NEXT_PUBLIC_COGNITO_ISSUER);
  const match = issuer.match(/^https:\/\/cognito-idp\.([a-z0-9-]+)\.amazonaws\.com\//);
  return match?.[1] ?? "";
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function errorMessage(raw: CognitoJson): string {
  const type = text(raw.__type).split("#").pop() || text(raw.code);
  switch (type) {
    case "NotAuthorizedException":
      return "メールアドレスまたはパスワードが正しくありません。";
    case "UserNotFoundException":
      return "メールアドレスまたはパスワードが正しくありません。";
    case "UserNotConfirmedException":
      return "アカウントの確認が完了していません。管理者に確認してください。";
    case "PasswordResetRequiredException":
      return "パスワード再設定が必要です。管理者に確認してください。";
    case "InvalidPasswordException":
      return "新しいパスワードがポリシーを満たしていません。";
    case "InvalidParameterException":
      return "入力内容を確認してください。";
    default:
      return text(raw.message) || "ログインに失敗しました。";
  }
}

async function cognitoRequest(target: "InitiateAuth" | "RespondToAuthChallenge", payload: CognitoJson) {
  const awsRegion = region();
  if (!awsRegion || !clientId()) {
    return { error: "ログイン設定が完了していません。管理者に確認してください。", status: 500 } as const;
  }
  const res = await fetch(`https://cognito-idp.${awsRegion}.amazonaws.com/`, {
    method: "POST",
    headers: {
      "content-type": "application/x-amz-json-1.1",
      "x-amz-target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(payload),
  });
  const body = (await res.json().catch(() => ({}))) as CognitoJson;
  if (!res.ok) {
    return { error: errorMessage(body), status: res.status === 400 ? 401 : res.status } as const;
  }
  return { body, status: 200 } as const;
}

function authResult(raw: CognitoJson) {
  const auth = raw.AuthenticationResult;
  const result = auth && typeof auth === "object" ? (auth as CognitoJson) : {};
  return {
    access_token: text(result.AccessToken),
    expires_in: typeof result.ExpiresIn === "number" ? result.ExpiresIn : 0,
    id_token: text(result.IdToken),
    token_type: text(result.TokenType),
  };
}

export async function POST(req: Request) {
  if (authMode() !== "cognito") {
    return NextResponse.json({ error: "ログインは現在利用できません。" }, { status: 403 });
  }
  const body = (await req.json().catch(() => ({}))) as CognitoJson;
  const action = text(body.action) || "sign_in";
  const username = text(body.email).toLowerCase();
  if (!username || username.length > 320) {
    return NextResponse.json({ error: "メールアドレスを入力してください。" }, { status: 400 });
  }

  if (action === "complete_new_password") {
    const challengeUsername = text(body.challenge_username) || username;
    const session = text(body.session);
    const newPassword = text(body.new_password);
    if (!session || !newPassword) {
      return NextResponse.json({ error: "新しいパスワードを入力してください。" }, { status: 400 });
    }
    const response = await cognitoRequest("RespondToAuthChallenge", {
      ChallengeName: "NEW_PASSWORD_REQUIRED",
      ClientId: clientId(),
      ChallengeResponses: {
        NEW_PASSWORD: newPassword,
        USERNAME: challengeUsername,
      },
      Session: session,
    });
    if ("error" in response) {
      return NextResponse.json({ error: response.error }, { status: response.status });
    }
    return NextResponse.json({ status: "authenticated", ...authResult(response.body) });
  }

  const password = text(body.password);
  if (!password) {
    return NextResponse.json({ error: "パスワードを入力してください。" }, { status: 400 });
  }
  const response = await cognitoRequest("InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    AuthParameters: {
      PASSWORD: password,
      USERNAME: username,
    },
    ClientId: clientId(),
  });
  if ("error" in response) {
    return NextResponse.json({ error: response.error }, { status: response.status });
  }
  const challengeName = text(response.body.ChallengeName);
  if (challengeName === "NEW_PASSWORD_REQUIRED") {
    const parameters =
      response.body.ChallengeParameters && typeof response.body.ChallengeParameters === "object"
        ? (response.body.ChallengeParameters as CognitoJson)
        : {};
    return NextResponse.json({
      challenge: "NEW_PASSWORD_REQUIRED",
      challenge_username: text(parameters.USER_ID_FOR_SRP) || username,
      required_attributes: stringArray(parameters.requiredAttributes),
      session: text(response.body.Session),
      status: "challenge",
    });
  }
  return NextResponse.json({ status: "authenticated", ...authResult(response.body) });
}
