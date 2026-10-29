/* smimp: process-based Java AST scanner, no dependency on the project's classpath. */
import java.io.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import javax.tools.*;
import com.sun.source.tree.*;
import com.sun.source.util.*;

public final class SmimpParser {
    private static final class Source extends SimpleJavaFileObject {
        final String contents;
        Source(String contents) {
            super(URI.create("string:///SmimpSource.java"), JavaFileObject.Kind.SOURCE);
            this.contents = contents;
        }
        @Override public CharSequence getCharContent(boolean ignoreEncodingErrors) { return contents; }
    }

    private static final class Types extends TreePathScanner<Void, Void> {
        final Set<String> names = new TreeSet<>();
        final Set<String> declared = new HashSet<>();
        void candidate(CharSequence value) {
            String word = value.toString();
            if (!word.isEmpty() && Character.isUpperCase(word.charAt(0)) && word.matches("[A-Za-z_$][A-Za-z0-9_$]*")) {
                names.add(word);
            }
        }
        void type(Tree t) {
            if (t == null) return;
            if (t instanceof IdentifierTree) {
                candidate(((IdentifierTree)t).getName());
            } else if (t instanceof MemberSelectTree) {
                // Map.Entry -> import Map; java.util.List is already qualified.
                ExpressionTree base = ((MemberSelectTree)t).getExpression();
                if (base instanceof IdentifierTree) candidate(((IdentifierTree)base).getName());
            } else if (t instanceof ParameterizedTypeTree) {
                ParameterizedTypeTree n = (ParameterizedTypeTree)t;
                type(n.getType());
                for (Tree arg : n.getTypeArguments()) type(arg);
            } else if (t instanceof ArrayTypeTree) {
                type(((ArrayTypeTree)t).getType());
            } else if (t instanceof AnnotatedTypeTree) {
                AnnotatedTypeTree n = (AnnotatedTypeTree)t;
                for (AnnotationTree a : n.getAnnotations()) scan(a, null);
                type(n.getUnderlyingType());
            } else if (t instanceof WildcardTree) {
                type(((WildcardTree)t).getBound());
            } else if (t instanceof UnionTypeTree) {
                for (Tree alt : ((UnionTypeTree)t).getTypeAlternatives()) type(alt);
            } else if (t instanceof IntersectionTypeTree) {
                for (Tree b : ((IntersectionTypeTree)t).getBounds()) type(b);
            } else if (t instanceof TypeParameterTree) {
                for (Tree b : ((TypeParameterTree)t).getBounds()) type(b);
                for (AnnotationTree a : ((TypeParameterTree)t).getAnnotations()) scan(a, null);
            }
        }
        @Override public Void visitImport(ImportTree node, Void unused) { return null; }
        @Override public Void visitClass(ClassTree node, Void unused) {
            declared.add(node.getSimpleName().toString());
            type(node.getExtendsClause());
            for (Tree t : node.getImplementsClause()) type(t);
            for (TypeParameterTree t : node.getTypeParameters()) type(t);
            return super.visitClass(node, unused);
        }
        @Override public Void visitTypeParameter(TypeParameterTree node, Void unused) {
            declared.add(node.getName().toString());
            return super.visitTypeParameter(node, unused);
        }
        @Override public Void visitMethod(MethodTree node, Void unused) {
            type(node.getReturnType());
            for (Tree t : node.getThrows()) type(t);
            for (TypeParameterTree t : node.getTypeParameters()) type(t);
            return super.visitMethod(node, unused);
        }
        @Override public Void visitVariable(VariableTree node, Void unused) {
            type(node.getType());
            return super.visitVariable(node, unused);
        }
        @Override public Void visitAnnotation(AnnotationTree node, Void unused) {
            type(node.getAnnotationType());
            return super.visitAnnotation(node, unused);
        }
        @Override public Void visitNewClass(NewClassTree node, Void unused) {
            type(node.getIdentifier());
            for (Tree t : node.getTypeArguments()) type(t);
            return super.visitNewClass(node, unused);
        }
        @Override public Void visitNewArray(NewArrayTree node, Void unused) {
            type(node.getType());
            return super.visitNewArray(node, unused);
        }
        @Override public Void visitTypeCast(TypeCastTree node, Void unused) {
            type(node.getType());
            return super.visitTypeCast(node, unused);
        }
        @Override public Void visitInstanceOf(InstanceOfTree node, Void unused) {
            type(node.getType());
            return super.visitInstanceOf(node, unused);
        }
        @Override public Void visitMemberSelect(MemberSelectTree node, Void unused) {
            ExpressionTree base = node.getExpression();
            if (base instanceof IdentifierTree) candidate(((IdentifierTree)base).getName());
            return super.visitMemberSelect(node, unused);
        }
        @Override public Void visitMemberReference(MemberReferenceTree node, Void unused) {
            ExpressionTree base = node.getQualifierExpression();
            if (base instanceof IdentifierTree) candidate(((IdentifierTree)base).getName());
            return super.visitMemberReference(node, unused);
        }
    }

    private static byte[] parse(String source) {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) return "@SMIMP_FAIL\n".getBytes(StandardCharsets.UTF_8);
        DiagnosticCollector<JavaFileObject> diagnostics = new DiagnosticCollector<>();
        try (StandardJavaFileManager manager = compiler.getStandardFileManager(diagnostics, null, StandardCharsets.UTF_8)) {
            JavacTask task = (JavacTask) compiler.getTask(null, manager, diagnostics,
                    List.of("-proc:none"), null, List.of(new Source(source)));
            Types visitor = new Types();
            for (CompilationUnitTree unit : task.parse()) visitor.scan(unit, null);
            visitor.names.removeAll(visitor.declared);
            String payload = "@SMIMP_OK\n" + String.join("\n", visitor.names);
            return payload.getBytes(StandardCharsets.UTF_8);
        } catch (Exception ex) {
            // Invalid/incomplete Java should not kill the parser process.
            return "@SMIMP_FAIL\n".getBytes(StandardCharsets.UTF_8);
        }
    }
    public static void main(String[] args) throws Exception {
        DataInputStream in = new DataInputStream(new BufferedInputStream(System.in));
        DataOutputStream out = new DataOutputStream(new BufferedOutputStream(System.out));
        while (true) {
            int size;
            try { size = in.readInt(); } catch (EOFException ex) { break; }
            if (size < 0 || size > 40_000_000) break;
            byte[] source = new byte[size];
            in.readFully(source);
            byte[] result = parse(new String(source, StandardCharsets.UTF_8));
            out.writeInt(result.length);
            out.write(result);
            out.flush();
        }
    }
}
